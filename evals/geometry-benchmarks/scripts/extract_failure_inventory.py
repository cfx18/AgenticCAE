"""Extract a scoped, read-only failure inventory from existing experiments."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


CAMPAIGNS = (
    "agent-geometry-30-sol-v2",
    "agent-geometry-30-sol-native-feedback-v3",
    "direct-codex-sol-ultra-omnimech2-https-20260914",
    "direct-codex-astra-ultra-omnimech2-https-20260914",
    "direct-kimi-k3-omnimech2-20260916",
    "direct-kimi-k3-omnimech4-20260916",
    "direct-kimi-k3-omnimech10-20260916",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    output = Path(args.output).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Output must remain inside the workspace")
    if output.exists():
        raise FileExistsError("Use a new output path to retain the previous snapshot")
    sources: dict[str, str] = {}

    def reference(path: str | Path) -> str:
        path = Path(path)
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Source outside workspace: {path}")
        key = path.relative_to(root).as_posix()
        if key not in sources:
            sources[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return key

    def read(path: str | Path):
        return json.loads((root / reference(path)).read_text(encoding="utf-8-sig"))

    manifest_path = ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    manifest = read(manifest_path)
    manifest_dir = Path(manifest_path).parent
    samples = {s["sample_id"]: s for s in manifest["samples"]}
    split = read("evals/geometry-benchmarks/splits/geometry-50-split-v1.json")
    membership = {s: k for k, rows in split["splits"].items() for s in rows}
    failures, scopes = [], []
    for campaign in CAMPAIGNS:
        result_path = f"evals/geometry-benchmarks/batch/{campaign}/results.json"
        results = read(result_path)
        scopes.append({
            "campaign": campaign, "result_source": result_path,
            "rows": len(results),
            "strict_failed": sum(r.get("passed") is False for r in results),
            "strict_passed": sum(r.get("passed") is True for r in results),
        })
        for row in results:
            if row.get("passed") is not False:
                continue
            sample = samples[row["sample_id"]]
            attempts = []
            for attempt in row["attempts"]:
                verdict = read(attempt["verdict"])
                attempts.append({
                    "attempt_id": attempt["attempt_id"],
                    "score": attempt["score"], "passed": attempt["passed"],
                    "elapsed_seconds": attempt.get("elapsed_seconds"),
                    "verdict": reference(attempt["verdict"]),
                    "checks": verdict.get("checks", {}),
                    "metrics": verdict.get("metrics", {}),
                    "decision": attempt.get("agent_decision"),
                    "decision_reason": attempt.get("decision_reason"),
                    "errors": attempt.get("errors", []),
                    "timed_out": attempt.get("timed_out"),
                    "decision_timed_out": attempt.get("decision_timed_out"),
                })
            failures.append({
                "case_id": f"{campaign}/{row['sample_id']}/{row['model']}",
                "source": {"path": result_path, "run_id": row["run_id"],
                           "job_dir": Path(row["job_dir"]).relative_to(root).as_posix()},
                "sample_id": row["sample_id"], "split": membership[row["sample_id"]],
                "model": row["model"], "reasoning_effort": row.get("reasoning_effort"),
                "protocol": row["protocol"], "loop_protocol": row["agent_loop_protocol"],
                "in_run_gt_feedback": not row["agent_loop_protocol"].startswith("native-"),
                "score": row["score"], "strict_pass": False,
                "selected_attempt_id": row["selected_attempt_id"],
                "stop_reason": row["stop_reason"],
                "candidate_sha256": row.get("candidate_sha256"),
                "input_images": [reference(manifest_dir / p) for p in sample["input_images"]],
                "gt_step": reference(manifest_dir / sample["ground_truth_step"]),
                "gt_code": reference(manifest_dir / sample["ground_truth_code"])
                if sample.get("ground_truth_code") else None,
                "attempts": attempts,
                "attribution_status": "unadjudicated_inventory",
            })

    # Counts describe tool calls, not unique images, elapsed time, or model attention.
    kimi = []
    for case in failures:
        if case["model"] != "kimi-k3":
            continue
        attempt_dir = root / case["source"]["job_dir"] / "attempts/a001"
        events_path = attempt_dir / "kimi-events.jsonl"
        counts: Counter[str] = Counter()
        image_calls, first_cad_line = [], None
        for line_no, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
            event = json.loads(line)
            for call in event.get("tool_calls") or []:
                function = call.get("function", {})
                name = function.get("name", "unknown")
                counts[name] += 1
                if name == "ReadMediaFile":
                    image_calls.append({"line": line_no, "arguments": json.loads(function["arguments"])})
                if name.endswith("autocad_core_start") and first_cad_line is None:
                    first_cad_line = line_no
        backend_events = []
        audit_path = attempt_dir / "mcp-audit.jsonl"
        for line_no, line in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), 1):
            event = json.loads(line)
            if event.get("tool") not in {"autocad_core_start", "autocad_core_status"}:
                continue
            for content in event.get("response", {}).get("result", {}).get("content", []):
                if content.get("type") != "text":
                    continue
                try:
                    payload = json.loads(content["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    backend_events.append({"line": line_no, "tool": event["tool"],
                        "timestamp": event.get("timestamp"), "job_id": payload.get("job_id"),
                        "status": payload.get("status"), "error": payload.get("error")})
        kimi.append({"case_id": case["case_id"], "events_source": reference(events_path),
            "audit_source": reference(audit_path), "tool_counts": dict(counts),
            "first_cad_start_line": first_cad_line, "image_calls": image_calls,
            "image_calls_before_first_cad": sum(
                c["line"] < first_cad_line for c in image_calls) if first_cad_line else None,
            "backend_events": backend_events})

    bench_path = "reports/generated/benchcad/sol-family-30-v2/analysis.json"
    bench = read(bench_path)
    bench_cases = [c for c in bench["cases"] if c["family"] in {
        "rect_frame", "sprocket", "duct_elbow", "table"}]
    review_path = "evals/geometry-benchmarks/human-reviews/agent-geometry-30-sol-v2.jsonl"
    reviews = []
    for line_no, line in enumerate((root / reference(review_path)).read_text(encoding="utf-8").splitlines(), 1):
        review = json.loads(line)
        reviews.append({"source": review_path, "line": line_no,
            "review_id": review["review_id"], "record_sha256": review["record_sha256"],
            "binding": review["binding"], "issue_types": review["issue_types"],
            "notes": review["notes"], "recommended_action": review["recommended_action"]})
    value = {
        "schema_version": "failure-inventory-draft-v1", "date": "2026-09-16",
        "scope": "Selected historical campaigns; not an exhaustive or independent benchmark",
        "notes": ["Low scores are observations, not causal model-failure labels.",
            "Scores from EvoCAD and BenchCAD are not on the same scale.",
            "Repeated samples across campaigns are not independent training examples.",
            "Validation samples remain diagnostic-only; no split was modified.",
            "Recorded decision reasons are agent reports, not verified causal explanations.",
            "Source hashes bind this extraction; existing review-chain validation is separate."],
        "campaign_scopes": scopes, "strict_failure_records": failures,
        "kimi_observation_sequences": kimi,
        "benchcad_selected_cases": {"source": bench_path, "metric": "official voxel IoU, [0,1]",
            "selection_rule": "Three final-vs-first regressions and table's checkpoint-selection regret",
            "posthoc_scores_fed_to_agent": bench["posthoc_gt_scores_fed_to_agent"], "cases": bench_cases},
        "human_reviews": reviews,
        "gt_attribution": read("evals/geometry-benchmarks/reference-runs/gt-attribution-00186338-r1.json"),
        "sources": sources,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "strict_failure_records": len(failures),
        "unique_geometry_samples": len({c['sample_id'] for c in failures}),
        "benchcad_cases": len(bench_cases), "bound_source_files": len(sources),
        "kimi_image_calls": {c['case_id']: len(c['image_calls']) for c in kimi}}, indent=2))


if __name__ == "__main__":
    main()
