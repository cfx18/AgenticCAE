"""Materialize durable-agent campaigns for reporting and paired review."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from typing import Any

from .geometry_report import generate_geometry_campaign_report


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_agent_campaign(campaign_dir: str | Path) -> dict[str, Any]:
    """Create deterministic compatibility inputs for existing report and review tools."""
    campaign_dir = Path(campaign_dir).resolve()
    agent_manifest_path = campaign_dir / "agent-campaign-manifest.json"
    agent_results_path = campaign_dir / "agent-results.json"
    plan_path = campaign_dir / "agent-plan.json"
    agent_manifest = _read_json(agent_manifest_path)
    agent_rows = _read_json(agent_results_path)
    plan = _read_json(plan_path)
    order = {job["sample_id"]: index for index, job in enumerate(plan["jobs"])}
    results = []
    for row in agent_rows:
        result_path = Path(row["result"]).resolve()
        if campaign_dir not in result_path.parents:
            raise ValueError(f"Agent result escapes campaign directory: {result_path}")
        result = _read_json(result_path)
        if result["sample_id"] != row["sample_id"]:
            raise ValueError(f"Agent result sample mismatch: {result_path}")
        if result["model"] != agent_manifest["model"]["name"]:
            raise ValueError(f"Agent result model mismatch: {result_path}")
        results.append(result)
    if len({row["sample_id"] for row in results}) != len(results):
        raise ValueError("Agent campaign contains duplicate sample results")
    results.sort(key=lambda row: order[row["sample_id"]])

    compatibility_manifest = {
        "schema_version": "1.0",
        "protocol": "evocad-geometry-v2",
        "agent_protocol": agent_manifest["protocol"],
        "agent_loop_protocol": "evocad-agent-loop-v2",
        "agent_condition": agent_manifest["agent_condition"],
        "campaign_id": agent_manifest["campaign_id"],
        "source_manifest_sha256": agent_manifest["source_manifest_sha256"],
        "models": [agent_manifest["model"]],
        "execution": agent_manifest["execution"],
        "benchmark_split": {
            "name": Path(agent_manifest["selection"]["path"]).stem,
            "split_sha256": agent_manifest["selection"]["selection_sha256"],
            "sample_count": agent_manifest["selection"]["sample_count"],
        },
        "runtime_environment": agent_manifest["runtime_environment"],
        "manifest_sha256": agent_manifest["campaign_manifest_sha256"],
    }
    _write_json_atomic(campaign_dir / "campaign-manifest.json", compatibility_manifest)
    _write_json_atomic(campaign_dir / "results.json", results)
    provenance = {
        "schema_version": "1.0",
        "complete": len(results) == agent_manifest["selection"]["sample_count"],
        "materialized_results": len(results),
        "agent_manifest_sha256": _sha256(agent_manifest_path),
        "agent_results_sha256": _sha256(agent_results_path),
        "plan_sha256": _sha256(plan_path),
        "report_source_sha256": _sha256(Path(__file__).resolve()),
    }
    _write_json_atomic(campaign_dir / "report-materialization.json", provenance)
    return {"manifest": compatibility_manifest, "results": results, "provenance": provenance}


def _run_metrics(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts", [])
    return {
        "score": float(result.get("score", 0.0)),
        "passed": bool(result.get("passed")),
        "first_score": float(attempts[0].get("score", 0.0)) if attempts else 0.0,
        "attempts": len(attempts),
        "elapsed_seconds": sum(float(row.get("elapsed_seconds", 0.0)) for row in attempts),
        "input_tokens": sum(
            int(row.get("usage", {}).get("input_tokens", 0) or 0) for row in attempts
        ),
        "output_tokens": sum(
            int(row.get("usage", {}).get("output_tokens", 0) or 0) for row in attempts
        ),
    }


def _sign_test_two_sided(gains: int, losses: int) -> float | None:
    discordant = gains + losses
    if not discordant:
        return None
    tail = sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1))
    return min(1.0, 2.0 * tail / (2 ** discordant))


def compare_sol_campaigns(
    candidate_results: list[dict[str, Any]], baseline_results: list[dict[str, Any]],
) -> dict[str, Any]:
    model = "gpt-5.6-sol"
    candidate = {row["sample_id"]: row for row in candidate_results if row["model"] == model}
    baseline = {row["sample_id"]: row for row in baseline_results if row["model"] == model}
    pairs = []
    for sample_id in sorted(candidate.keys() & baseline.keys()):
        new = _run_metrics(candidate[sample_id])
        old = _run_metrics(baseline[sample_id])
        pairs.append({
            "sample_id": sample_id,
            "baseline_score": old["score"],
            "candidate_score": new["score"],
            "score_delta": round(new["score"] - old["score"], 4),
            "baseline_passed": old["passed"],
            "candidate_passed": new["passed"],
            "baseline_first_score": old["first_score"],
            "candidate_first_score": new["first_score"],
            "baseline_attempts": old["attempts"],
            "candidate_attempts": new["attempts"],
            "elapsed_delta_seconds": round(new["elapsed_seconds"] - old["elapsed_seconds"], 3),
            "input_token_delta": new["input_tokens"] - old["input_tokens"],
            "output_token_delta": new["output_tokens"] - old["output_tokens"],
        })
    gains = sum(not row["baseline_passed"] and row["candidate_passed"] for row in pairs)
    losses = sum(row["baseline_passed"] and not row["candidate_passed"] for row in pairs)
    deltas = [row["score_delta"] for row in pairs]
    return {
        "schema_version": "1.0",
        "model": model,
        "paired_samples": len(pairs),
        "baseline_strict_passes": sum(row["baseline_passed"] for row in pairs),
        "candidate_strict_passes": sum(row["candidate_passed"] for row in pairs),
        "strict_pass_gains": gains,
        "strict_pass_losses": losses,
        "paired_sign_test_p": _sign_test_two_sided(gains, losses),
        "mean_score_delta": round(statistics.mean(deltas), 4) if deltas else None,
        "median_score_delta": round(statistics.median(deltas), 4) if deltas else None,
        "interpretation": (
            "Descriptive paired rerun only. The durable-kernel compatibility condition keeps "
            "the inner modeling policy unchanged, so differences are not a causal Agent-architecture effect."
        ),
        "pairs": pairs,
    }


def summarize_long_horizon_outcomes(results: list[dict[str, Any]]) -> dict[str, Any]:
    stop_reasons = Counter(str(row.get("stop_reason") or "unknown") for row in results)
    safety_reasons = {"max_iterations", "job_time_budget", "action_timeout"}
    runtime_reasons = {"decision_unavailable", "action_unavailable", "verifier_error"}
    censored = [
        row for row in results
        if row.get("agent_requested_continue") and row.get("stop_reason") in safety_reasons
    ]
    runtime_censored = [row for row in results if row.get("stop_reason") in runtime_reasons]
    selected_rollback = 0
    improved = 0
    attempts = 0
    for row in results:
        trajectory = row.get("attempts", [])
        attempts += len(trajectory)
        if trajectory and float(row.get("score", 0.0)) > float(trajectory[0].get("score", 0.0)):
            improved += 1
        if trajectory and row.get("selected_attempt_id") != trajectory[-1].get("attempt_id"):
            selected_rollback += 1
    by_dataset = []
    for dataset in sorted({row["sample_id"].split(":", 1)[0] for row in results}):
        subset = [row for row in results if row["sample_id"].split(":", 1)[0] == dataset]
        subset_attempts = [len(row.get("attempts", [])) for row in subset]
        first_scores = [
            float(row["attempts"][0].get("score", 0.0))
            for row in subset if row.get("attempts")
        ]
        strict = sum(bool(row.get("passed")) for row in subset)
        by_dataset.append({
            "dataset": dataset,
            "runs": len(subset),
            "strict_passes": strict,
            "strict_pass_rate": round(100.0 * strict / len(subset), 2),
            "first_attempt_mean": round(statistics.mean(first_scores), 2) if first_scores else None,
            "selected_mean": round(
                statistics.mean(float(row.get("score", 0.0)) for row in subset), 2,
            ),
            "mean_attempts": round(statistics.mean(subset_attempts), 3),
            "safety_censored_runs": sum(row in censored for row in subset),
        })
    return {
        "schema_version": "1.0",
        "runs": len(results),
        "stop_reasons": dict(sorted(stop_reasons.items())),
        "autonomous_stops": stop_reasons.get("agent_stop", 0),
        "strict_pass_stops": stop_reasons.get("strict_pass", 0),
        "safety_censored_runs": len(censored),
        "safety_censored_sample_ids": [row["sample_id"] for row in censored],
        "runtime_censored_runs": len(runtime_censored),
        "runtime_censored_sample_ids": [row["sample_id"] for row in runtime_censored],
        "runs_improved_over_first_attempt": improved,
        "best_checkpoint_rollbacks": selected_rollback,
        "total_attempts": attempts,
        "mean_attempts": round(attempts / len(results), 3) if results else None,
        "near_threshold_failures": sum(
            not row.get("passed") and float(row.get("score", 0.0)) >= 99.0
            for row in results
        ),
        "run_integrity_failures": sum(not row.get("integrity", {}).get("ok", False) for row in results),
        "by_dataset": by_dataset,
    }


def generate_agent_geometry_report(
    campaign_dir: str | Path,
    output_dir: str | Path,
    *,
    baseline_dir: str | Path | None = None,
) -> dict[str, Any]:
    campaign_dir = Path(campaign_dir).resolve()
    output_dir = Path(output_dir).resolve()
    materialized = materialize_agent_campaign(campaign_dir)
    summary = generate_geometry_campaign_report(campaign_dir, output_dir)
    trajectory_summary = summarize_long_horizon_outcomes(materialized["results"])
    _write_json_atomic(output_dir / "agent-trajectory-summary.json", trajectory_summary)
    comparison = None
    if baseline_dir is not None:
        baseline_results = _read_json(Path(baseline_dir).resolve() / "results.json")
        comparison = compare_sol_campaigns(materialized["results"], baseline_results)
        _write_json_atomic(output_dir / "paired-sol-comparison.json", comparison)
        rows = comparison["pairs"]
        with (output_dir / "paired-sol-comparison.csv").open(
            "w", newline="", encoding="utf-8",
        ) as stream:
            fieldnames = list(rows[0]) if rows else ["sample_id"]
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return {
        "summary": summary,
        "trajectory_summary": trajectory_summary,
        "comparison": comparison,
        "materialization": materialized["provenance"],
    }
