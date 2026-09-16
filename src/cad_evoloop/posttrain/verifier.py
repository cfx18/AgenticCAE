"""Private, task-specific grading; never trust candidate self-reported geometry."""

from __future__ import annotations

import json
import math
from pathlib import Path
import unicodedata

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from .bundle import contained_file, validate_bundle
from .environment import Episode


def normalize_answer(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().strip().rstrip(".\u3002").split())


def check_answer(actual: dict, expected: dict, tolerance: float,
                 accepted_answers: dict[str, list[str]] | None = None) -> dict[str, bool]:
    checks = {}
    for name, value in expected.items():
        candidate = actual.get(name)
        if isinstance(value, bool):
            passed = type(candidate) is bool and candidate == value
        elif isinstance(value, (int, float)):
            passed = (isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                      and math.isfinite(candidate) and abs(candidate - value) <= tolerance)
        elif isinstance(value, str) and accepted_answers and name in accepted_answers:
            aliases = accepted_answers[name]
            if not isinstance(aliases, list) or not all(isinstance(item, str) and item.strip() for item in aliases):
                raise ValueError("Invalid predeclared answer aliases")
            passed = isinstance(candidate, str) and normalize_answer(candidate) in {
                normalize_answer(item) for item in [value, *aliases]}
        else:
            passed = type(candidate) is type(value) and candidate == value
        checks[name] = passed
    return checks


def grade_files(task: Path, *, answer: Path | None = None, model: Path | None = None) -> dict:
    validate_bundle(task)
    verifier = json.loads((task / "private/verifier.json").read_text(encoding="utf-8"))
    if verifier["kind"] == "ungraded_answer":
        valid = False
        if answer is not None:
            try:
                value = json.loads(answer.read_text(encoding="utf-8"))
                valid = isinstance(value, dict) and isinstance(value.get("answer"), str) and bool(value["answer"].strip())
            except (json.JSONDecodeError, UnicodeError):
                pass
        return {"passed": None, "score": None, "checks": {"valid_answer_submission": valid},
                "human_review_required": True, "protocol": "ungraded-drawing-probe-v1",
                "reason": "No independent reference label. Submission validity is not correctness."}
    if verifier["kind"] == "json_fields":
        if answer is None:
            return {"passed": False, "score": 0.0, "checks": {"answer_submitted": False}}
        try:
            value = json.loads(answer.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            return {"passed": False, "score": 0.0, "checks": {"valid_json": False}}
        if not isinstance(value, dict):
            return {"passed": False, "score": 0.0, "checks": {"json_object": False}}
        checks = check_answer(value, verifier["expected"], verifier.get("absolute_tolerance", 1e-3),
                              verifier.get("accepted_answers"))
        unmatched = [name for name in verifier.get("accepted_answers", {})
                     if isinstance(verifier["expected"].get(name), str)
                     and isinstance(value.get(name), str) and not checks[name]]
        return {"passed": None if unmatched else all(checks.values()), "checks": checks,
                "score": None if unmatched else sum(checks.values()) / len(checks), "protocol": "task-fields-v1",
                **({"human_review_required": True, "unmatched_text_fields": unmatched,
                    "reason": "Unlisted free-text answer; lexical mismatch is not a verified semantic error."}
                   if unmatched else {})}
    if verifier["kind"] != "fixed_frame_brep":
        raise ValueError("Unknown verifier kind")
    if model is None:
        return {"passed": False, "score": 0.0, "checks": {"model_submitted": False}}
    from .geometry import load_shape, shape_verdict

    # Bad GT is an infrastructure/data error, not a model negative reward.
    target = load_shape(contained_file(task, verifier["target"]))
    try:
        candidate = load_shape(model)
    except (ValueError, RuntimeError):
        return {"passed": False, "score": 0.0, "checks": {"valid_step": False}}
    return shape_verdict(candidate, target, volume_tolerance=verifier["volume_tolerance_mm3"],
                         length_tolerance=verifier["length_tolerance_mm"])


def grade_episode(task: Path, episode: Episode) -> dict:
    state = json.loads((episode.root / "episode.json").read_text(encoding="utf-8"))
    if state["status"] != "submitted":
        raise ValueError("Grade an explicit final submission, not a best intermediate")
    if sha256_file(task / "manifest.json") != state["task_manifest_sha256"]:
        raise ValueError("Task binding changed")
    for asset in state["public_inventory"]:
        if sha256_file(contained_file(episode.root / "input", asset["path"])) != asset["sha256"]:
            raise ValueError("Agent input changed after reset")
    paths = {}
    for artifact in state["submission"]["files"]:
        path = contained_file(episode.root, artifact["snapshot"])
        if sha256_file(path) != artifact["sha256"]:
            raise ValueError("Submitted snapshot changed")
        paths[artifact["source"]] = path
    verdict = grade_files(task, answer=paths.get("answer.json"), model=paths.get("model.step"))
    verdict.update({"task_manifest_sha256": state["task_manifest_sha256"],
                    "submission": state["submission"], "episode_id": state["episode_id"]})
    # Numeric reward and GT-derived diagnostics remain evaluator-side.
    write_json_atomic(episode.root / "private-verdict.json", verdict)
    episode.record("private_verification_completed", {"verdict_sha256": sha256_file(episode.root / "private-verdict.json")})
    return verdict
