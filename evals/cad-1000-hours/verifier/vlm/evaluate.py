"""Evaluate deterministic-verifier gaps with image evidence from Codex VLM."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from .provider import CodexCliProvider


PROMPT_VERSION = "cad-vlm-1"


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
            and float(item.get("confidence", 0)) >= confidence_threshold
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
    parser.add_argument("--ledger-run")
    parser.add_argument("--attempt")
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir).resolve()
    deterministic_path = Path(args.deterministic_verdict).resolve()
    output = Path(args.output).resolve()
    work_dir = Path(args.work_dir).resolve() if args.work_dir else output.parent / "vlm-work"
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
    candidate_images = [Path(path).resolve() for path in args.candidate_image]
    reference_images = [Path(path).resolve() for path in args.reference_image]
    images = [*candidate_images, *reference_images]
    for image in images:
        if not image.is_file():
            raise FileNotFoundError(image)
    roles = [
        *[f"candidate:{image.name}" for image in candidate_images],
        *[f"reference:{image.name}" for image in reference_images],
    ]
    prompt = build_prompt(task, targets, roles)
    schema_path = Path(__file__).with_name("visual-verdict.schema.json")
    provider = CodexCliProvider(model=args.model)
    raw, provider_metadata = provider.evaluate(
        prompt, images, schema_path, work_dir, [item["id"] for item in targets],
    )
    combined = merge_visual_result(
        deterministic, raw, [item["id"] for item in targets], args.confidence_threshold,
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
        "combined": combined,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if bool(args.ledger_run) != bool(args.attempt):
        raise ValueError("--ledger-run and --attempt must be supplied together")
    if args.ledger_run:
        eval_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(eval_root))
        from runledger import RunLedger

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
