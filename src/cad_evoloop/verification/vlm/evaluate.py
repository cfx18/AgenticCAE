"""Evaluate deterministic-verifier gaps with image evidence from Codex VLM."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import math
from typing import Any

from .provider import CodexCliProvider
from ...ledger import RunLedger
from ...paths import evaluation_root


PROMPT_VERSION = "cad-vlm-1"
CONSENSUS_VOTE_FLOOR = 0.65
CONSENSUS_CONFIDENCE_FLOOR = 0.70


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_prompt(task: dict[str, Any], rubrics: list[dict[str, Any]], image_roles: list[str]) -> str:
    return "\n".join([
        "You are a conservative visual QA evaluator for an AutoCAD drawing.",
        "Evaluate only the attached images. Do not call tools, inspect files, or infer hidden geometry.",
        "The images are attached in this exact order:",
        *[f"{index + 1}. {role}" for index, role in enumerate(image_roles)],
        "Candidate images show the produced drawing. Reference images show the intended result.",
        "Judge only the listed rubrics. Ignore cosmetic differences unless a rubric requires them.",
        "Use pass only when visible evidence is clear, fail only when a visible contradiction is clear, and uncertain otherwise.",
        "Evidence regions use normalized image coordinates with origin at the top-left.",
        f"Task: {task.get('task', '')}",
        f"Description: {task.get('description', '')}",
        "Rubrics JSON:",
        json.dumps([{"id": item["id"], "requirement": item["requirement"]} for item in rubrics], ensure_ascii=False),
    ])


def merge_visual_result(
    deterministic: dict[str, Any],
    visual: dict[str, Any],
    target_ids: list[str],
    confidence_threshold: float,
) -> dict[str, Any]:
    groups = [deterministic.get("hard_gates", []), deterministic.get("dimensions", []), deterministic.get("rubrics", [])]
    total = sum(len(group) for group in groups)
    verified_before = sum(
        1 for group in groups for item in group if item.get("status") != "unverified"
    )
    resolved = []
    unresolved = []
    for item in visual.get("rubrics", []):
        accepted = (
            visual.get("image_quality") == "sufficient"
            and item.get("verdict") in {"pass", "fail"}
            and (
                float(item.get("confidence", 0)) >= confidence_threshold
                or item.get("accepted_by_consensus") is True
            )
        )
        record = {**item, "accepted": accepted}
        (resolved if accepted else unresolved).append(record)
    resolved_ids = {item["id"] for item in resolved}
    missing_ids = sorted(set(target_ids) - resolved_ids)
    resolved_failures = [item for item in resolved if item["verdict"] == "fail"]
    coverage_after = round(100.0 * (verified_before + len(resolved_ids)) / total, 2) if total else 100.0
    if not deterministic.get("passed", False):
        decision = "fail"
    elif resolved_failures:
        decision = "fail"
    elif missing_ids:
        decision = "incomplete"
    else:
        decision = "pass"
    return {
        "decision": decision,
        "deterministic_passed": deterministic.get("passed", False),
        "coverage_before": deterministic.get("coverage"),
        "coverage_after": coverage_after,
        "confidence_threshold": confidence_threshold,
        "resolved": resolved,
        "unresolved": unresolved,
        "missing_rubric_ids": missing_ids,
        "visual_failures": [item["id"] for item in resolved_failures],
    }


def aggregate_visual_results(
    evaluations: list[dict[str, Any]],
    target_ids: list[str],
    *,
    vote_floor: float = CONSENSUS_VOTE_FLOOR,
    confidence_floor: float = CONSENSUS_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Aggregate repeated visual judgments without treating one weak vote as evidence."""
    if not evaluations:
        raise ValueError("At least one visual evaluation is required")
    if len(evaluations) == 1:
        return evaluations[0]
    required_votes = math.ceil(2 * len(evaluations) / 3)
    rubrics = []
    for rubric_id in target_ids:
        items = [
            next((item for item in value.get("rubrics", []) if item.get("id") == rubric_id), None)
            for value in evaluations
            if value.get("image_quality") == "sufficient"
        ]
        items = [item for item in items if item is not None]
        eligible = [
            item for item in items
            if item.get("verdict") in {"pass", "fail"}
            and float(item.get("confidence", 0)) >= vote_floor
        ]
        counts = {
            verdict: sum(item.get("verdict") == verdict for item in eligible)
            for verdict in ("pass", "fail")
        }
        winner = max(counts, key=counts.get) if eligible else "uncertain"
        winning = [item for item in eligible if item.get("verdict") == winner]
        mean_confidence = (
            sum(float(item.get("confidence", 0)) for item in winning) / len(winning)
            if winning else 0.0
        )
        accepted = (
            winner in {"pass", "fail"}
            and counts[winner] >= required_votes
            and mean_confidence >= confidence_floor
        )
        exemplar = max(winning, key=lambda item: float(item.get("confidence", 0))) if winning else None
        rubrics.append({
            "id": rubric_id,
            "verdict": winner if accepted else "uncertain",
            "confidence": round(mean_confidence, 4),
            "explanation": (
                f"Consensus {counts['pass']} pass / {counts['fail']} fail from "
                f"{len(evaluations)} evaluations. "
                + (exemplar.get("explanation", "") if exemplar else "No eligible visual vote.")
            ),
            "evidence": exemplar.get("evidence", []) if exemplar else [],
            "accepted_by_consensus": accepted,
            "consensus": {
                "evaluations": len(evaluations),
                "required_votes": required_votes,
                "eligible_votes": len(eligible),
                "pass_votes": counts["pass"],
                "fail_votes": counts["fail"],
                "vote_confidence_floor": vote_floor,
                "mean_winning_confidence": round(mean_confidence, 4),
                "confidence_floor": confidence_floor,
            },
        })
    sufficient = sum(value.get("image_quality") == "sufficient" for value in evaluations)
    return {
        "image_quality": "sufficient" if sufficient >= required_votes else "insufficient",
        "rubrics": rubrics,
        "global_notes": (
            f"Consensus aggregation over {len(evaluations)} isolated visual evaluations; "
            f"{sufficient} reported sufficient image quality."
        ),
    }


def _aggregate_provider_metadata(providers: list[dict[str, Any]], model: str) -> dict[str, Any]:
    usage_keys = (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens",
    )
    return {
        "provider": "visual-consensus",
        "model": model,
        "evaluations": providers,
        "evaluation_count": len(providers),
        "elapsed_seconds": round(sum(float(item.get("elapsed_seconds", 0)) for item in providers), 3),
        "usage": {
            key: sum(int(item.get("usage", {}).get(key, 0) or 0) for item in providers)
            for key in usage_keys
        },
    }


def evaluate_visual_gaps(
    *,
    sample_dir: Path,
    deterministic_path: Path,
    candidate_images: list[Path],
    reference_images: list[Path],
    output: Path,
    work_dir: Path,
    model: str = "gpt-5.5",
    confidence_threshold: float = 0.85,
    max_evaluations: int = 1,
) -> dict[str, Any]:
    """Resolve deterministic rubric gaps with an isolated image-only evaluator."""
    sample_dir = Path(sample_dir).resolve()
    deterministic_path = Path(deterministic_path).resolve()
    output = Path(output).resolve()
    work_dir = Path(work_dir).resolve()
    task = json.loads((sample_dir / "task_desc.json").read_text(encoding="utf-8"))
    rubric_document = json.loads((sample_dir / "rubrics.json").read_text(encoding="utf-8"))
    deterministic = json.loads(deterministic_path.read_text(encoding="utf-8"))
    deterministic_rubrics = {item["id"]: item for item in deterministic.get("rubrics", [])}
    targets = [
        item for item in rubric_document.get("rubrics", [])
        if deterministic_rubrics.get(item["id"], {}).get("status") == "unverified"
    ]
    if not targets:
        raise ValueError("No unverified rubrics require visual evaluation")
    if max_evaluations < 1 or max_evaluations == 2:
        raise ValueError("max_evaluations must be 1 or at least 3")
    candidate_images = [Path(path).resolve() for path in candidate_images]
    reference_images = [Path(path).resolve() for path in reference_images]
    images = [*candidate_images, *reference_images]
    if not candidate_images or not reference_images:
        raise ValueError("Visual evaluation requires candidate and reference images")
    for image in images:
        if not image.is_file():
            raise FileNotFoundError(image)
    roles = [
        *[f"candidate:{image.name}" for image in candidate_images],
        *[f"reference:{image.name}" for image in reference_images],
    ]
    prompt = build_prompt(task, targets, roles)
    schema_path = Path(__file__).resolve().parents[1] / "schemas/visual-verdict.schema.json"
    target_ids = [item["id"] for item in targets]
    raw_evaluations = []
    provider_evaluations = []
    for index in range(max_evaluations):
        judge_work_dir = work_dir if max_evaluations == 1 else work_dir / f"judge-{index + 1:02d}"
        raw, provider_metadata = CodexCliProvider(model=model).evaluate(
            prompt, images, schema_path, judge_work_dir, target_ids,
        )
        raw_evaluations.append(raw)
        provider_evaluations.append(provider_metadata)
    raw = aggregate_visual_results(raw_evaluations, target_ids)
    provider_metadata = (
        provider_evaluations[0]
        if len(provider_evaluations) == 1
        else _aggregate_provider_metadata(provider_evaluations, model)
    )
    combined = merge_visual_result(
        deterministic, raw, target_ids, confidence_threshold,
    )
    result = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "passed": combined["decision"] == "pass",
        "score": deterministic.get("score"),
        "coverage": combined["coverage_after"],
        "prompt_version": PROMPT_VERSION,
        "provider": provider_metadata,
        "images": [
            {"role": role, "path": str(path), "sha256": sha256(path)}
            for role, path in zip(roles, images)
        ],
        "target_rubric_ids": [item["id"] for item in targets],
        "visual": raw,
        "evaluations": raw_evaluations,
        "consensus_policy": {
            "max_evaluations": max_evaluations,
            "actual_evaluations": len(raw_evaluations),
            "single_confidence_threshold": confidence_threshold,
            "vote_confidence_floor": CONSENSUS_VOTE_FLOOR,
            "consensus_confidence_floor": CONSENSUS_CONFIDENCE_FLOOR,
        },
        "combined": combined,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--deterministic-verdict", required=True)
    parser.add_argument("--candidate-image", action="append", required=True)
    parser.add_argument("--reference-image", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir")
    parser.add_argument("--model", default=os.environ.get("CAD_VLM_MODEL", "gpt-5.5"))
    parser.add_argument("--confidence-threshold", type=float, default=0.85)
    parser.add_argument("--max-evaluations", type=int, default=3)
    parser.add_argument("--ledger-run")
    parser.add_argument("--attempt")
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir).resolve()
    output = Path(args.output).resolve()
    result = evaluate_visual_gaps(
        sample_dir=sample_dir,
        deterministic_path=Path(args.deterministic_verdict),
        candidate_images=[Path(path) for path in args.candidate_image],
        reference_images=[Path(path) for path in args.reference_image],
        output=output,
        work_dir=Path(args.work_dir).resolve() if args.work_dir else output.parent / "vlm-work",
        model=args.model,
        confidence_threshold=args.confidence_threshold,
        max_evaluations=args.max_evaluations,
    )
    combined = result["combined"]

    if bool(args.ledger_run) != bool(args.attempt):
        raise ValueError("--ledger-run and --attempt must be supplied together")
    if args.ledger_run:
        eval_root = evaluation_root(__file__)
        ledger = RunLedger(eval_root)
        ledger.add_artifact(args.ledger_run, args.attempt, output, role="vlm-verdict")
        ledger.event(
            args.ledger_run,
            "vlm.completed",
            f"Visual evaluator decision: {combined['decision']}",
            status="pass" if combined["decision"] == "pass" else combined["decision"],
            actor="vlm-verifier",
            attempt_id=args.attempt,
            payload={
                "model": args.model,
                "prompt_version": PROMPT_VERSION,
                "coverage_before": combined["coverage_before"],
                "coverage_after": combined["coverage_after"],
                "visual_failures": combined["visual_failures"],
            },
        )
    print(json.dumps({
        "decision": combined["decision"],
        "coverage_before": combined["coverage_before"],
        "coverage_after": combined["coverage_after"],
        "output": str(output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
