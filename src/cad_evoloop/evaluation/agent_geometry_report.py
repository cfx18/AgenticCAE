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

from PIL import Image, ImageDraw

from .geometry_report import _font, generate_geometry_campaign_report


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
    blocked_work_units = []
    for row in agent_rows:
        if row.get("result") is None:
            if row.get("work_unit_status") != "blocked":
                raise ValueError(
                    f"Agent row has no result outside a blocked work unit: {row['sample_id']}"
                )
            blocked_work_units.append({
                "sample_id": row["sample_id"],
                "project_id": row.get("project_id"),
                "project_status": row.get("project_status"),
                "work_unit_status": row["work_unit_status"],
                "stop_reason": row.get("stop_reason"),
                "clarification_questions": row.get("clarification_questions", []),
                "project_integrity": row.get("project_integrity"),
            })
            continue
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

    loop_protocols = {
        row.get("agent_loop_protocol") for row in results if row.get("agent_loop_protocol")
    }
    if len(loop_protocols) > 1:
        raise ValueError("Agent campaign mixes agent-loop protocols")
    compatibility_manifest = {
        "schema_version": "1.0",
        "protocol": "evocad-geometry-v2",
        "agent_protocol": agent_manifest["protocol"],
        "agent_loop_protocol": next(iter(loop_protocols), "evocad-agent-loop-v2"),
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
        "complete": (
            len(results) == agent_manifest["selection"]["sample_count"]
            and not blocked_work_units
        ),
        "materialized_results": len(results),
        "blocked_work_units": sorted(
            blocked_work_units, key=lambda row: order[row["sample_id"]],
        ),
        "agent_manifest_sha256": _sha256(agent_manifest_path),
        "agent_results_sha256": _sha256(agent_results_path),
        "plan_sha256": _sha256(plan_path),
        "report_source_sha256": _sha256(Path(__file__).resolve()),
        "report_source_hashes": {
            "agent_geometry_report.py": _sha256(Path(__file__).resolve()),
            "geometry_report.py": _sha256(Path(__file__).with_name("geometry_report.py")),
        },
    }
    _write_json_atomic(campaign_dir / "report-materialization.json", provenance)
    return {"manifest": compatibility_manifest, "results": results, "provenance": provenance}


def _run_metrics(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts", [])
    return {
        "score": float(result.get("score", 0.0)),
        "passed": bool(result.get("passed")),
        "first_score": float(attempts[0].get("score", 0.0)) if attempts else 0.0,
        "first_passed": bool(attempts[0].get("passed")) if attempts else False,
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
    by_dataset = []
    for dataset in sorted({row["sample_id"].split(":", 1)[0] for row in pairs}):
        subset = [row for row in pairs if row["sample_id"].startswith(dataset + ":")]
        by_dataset.append({
            "dataset": dataset,
            "paired_samples": len(subset),
            "baseline_strict_passes": sum(row["baseline_passed"] for row in subset),
            "candidate_strict_passes": sum(row["candidate_passed"] for row in subset),
            "mean_score_delta": round(statistics.mean(row["score_delta"] for row in subset), 4),
        })
    baseline_metrics = [_run_metrics(baseline[sample_id]) for sample_id in sorted(candidate.keys() & baseline.keys())]
    candidate_metrics = [_run_metrics(candidate[sample_id]) for sample_id in sorted(candidate.keys() & baseline.keys())]
    return {
        "schema_version": "1.0",
        "model": model,
        "paired_samples": len(pairs),
        "baseline_strict_passes": sum(row["baseline_passed"] for row in pairs),
        "candidate_strict_passes": sum(row["candidate_passed"] for row in pairs),
        "baseline_pass_at_1": sum(row["first_passed"] for row in baseline_metrics),
        "candidate_pass_at_1": sum(row["first_passed"] for row in candidate_metrics),
        "baseline_selected_mean": round(statistics.mean(row["score"] for row in baseline_metrics), 4) if pairs else None,
        "candidate_selected_mean": round(statistics.mean(row["score"] for row in candidate_metrics), 4) if pairs else None,
        "baseline_mean_attempts": round(statistics.mean(row["attempts"] for row in baseline_metrics), 4) if pairs else None,
        "candidate_mean_attempts": round(statistics.mean(row["attempts"] for row in candidate_metrics), 4) if pairs else None,
        "strict_pass_gains": gains,
        "strict_pass_losses": losses,
        "paired_sign_test_p": _sign_test_two_sided(gains, losses),
        "mean_score_delta": round(statistics.mean(deltas), 4) if deltas else None,
        "median_score_delta": round(statistics.median(deltas), 4) if deltas else None,
        "by_dataset": by_dataset,
        "interpretation": (
            "Descriptive paired historical comparison with the same model and frozen samples. "
            "It is not randomized and may include multiple implementation changes, so it does not "
            "by itself identify which Agent component caused the difference."
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


def render_agent_evaluation_figure(
    results: list[dict[str, Any]],
    campaign_summary: dict[str, Any],
    trajectory_summary: dict[str, Any],
) -> Image.Image:
    """Render the fixed-model closed-loop result as a paper-ready four-panel figure."""
    width, height = 1800, 1100
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font = _font(38, bold=True)
    panel_font = _font(23, bold=True)
    metric_font = _font(32, bold=True)
    body_font = _font(17)
    small_font = _font(14)
    colors = {
        "ink": "#182126", "muted": "#5C6770", "grid": "#DDE3E6",
        "teal": "#087F8C", "orange": "#D96C06", "green": "#25834A",
        "red": "#B43A33", "gray": "#98A2A8", "light": "#EEF2F3",
    }

    draw.text((74, 40), "EvoCAD Closed-Loop Geometry Evaluation", fill=colors["ink"], font=title_font)
    draw.text(
        (76, 92),
        f"Fixed model: gpt-5.6-sol  |  frozen dev+validation selection  |  "
        f"n={campaign_summary['runs']}  |  strict geometry protocol",
        fill=colors["muted"], font=body_font,
    )
    draw.line((74, 132, 1726, 132), fill=colors["ink"], width=2)
    draw.line((880, 170, 880, 1010), fill=colors["grid"], width=2)
    draw.line((74, 600, 1726, 600), fill=colors["grid"], width=2)

    # A. Closed-loop recovery headline.
    draw.text((76, 172), "A  Closed-loop recovery", fill=colors["ink"], font=panel_font)
    runs = max(1, int(campaign_summary["runs"]))
    pass1 = int(campaign_summary["pass_at_1"])
    final_pass = int(campaign_summary["strict_passes"])
    bar_left, bar_right = 104, 790
    bar_width = bar_right - bar_left
    rows = [
        ("Pass@1", pass1, colors["gray"]),
        ("Final strict", final_pass, colors["green"]),
    ]
    for index, (label, value, color) in enumerate(rows):
        y = 262 + index * 118
        draw.text((104, y - 35), label, fill=colors["ink"], font=body_font)
        draw.rounded_rectangle((bar_left, y, bar_right, y + 48), radius=5, fill=colors["light"])
        draw.rounded_rectangle(
            (bar_left, y, bar_left + bar_width * value / runs, y + 48), radius=5, fill=color,
        )
        draw.text(
            (bar_right - 170, y + 7), f"{value}/{runs}  {100 * value / runs:.1f}%",
            fill=colors["ink"], font=body_font,
        )
    recovered = final_pass - pass1
    draw.text((104, 507), f"+{recovered} strict recoveries", fill=colors["green"], font=metric_font)
    draw.text(
        (443, 518),
        f"mean score {campaign_summary['first_attempt_mean']:.2f} -> "
        f"{campaign_summary['selected_mean']:.2f}",
        fill=colors["muted"], font=body_font,
    )

    # B. Every sample: first score versus selected checkpoint.
    draw.text((920, 172), "B  Feedback recovery by sample", fill=colors["ink"], font=panel_font)
    left, top, right, bottom = 980, 238, 1665, 548
    for tick in range(0, 101, 20):
        x = left + (right - left) * tick / 100
        y = bottom - (bottom - top) * tick / 100
        draw.line((x, top, x, bottom), fill=colors["grid"], width=1)
        draw.line((left, y, right, y), fill=colors["grid"], width=1)
        draw.text((x - 10, bottom + 12), str(tick), fill=colors["muted"], font=small_font)
        draw.text((left - 36, y - 8), str(tick), fill=colors["muted"], font=small_font)
    draw.line((left, bottom, right, top), fill=colors["gray"], width=2)
    for result in results:
        attempts = result.get("attempts", [])
        if not attempts:
            continue
        first = float(attempts[0].get("score", 0.0))
        selected = float(result.get("score", 0.0))
        x = left + (right - left) * first / 100
        y = bottom - (bottom - top) * selected / 100
        color = colors["orange"] if result["sample_id"].startswith("omnimech:") else colors["teal"]
        radius = 7 if selected > first + 0.01 else 5
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="#FFFFFF", width=2)
    draw.text((1210, 575), "First-attempt score", fill=colors["muted"], font=small_font)
    draw.text((980, 208), "Selected checkpoint score", fill=colors["muted"], font=small_font)
    draw.ellipse((1450, 185, 1464, 199), fill=colors["teal"])
    draw.text((1471, 184), "Ortho2CAD", fill=colors["muted"], font=small_font)
    draw.ellipse((1570, 185, 1584, 199), fill=colors["orange"])
    draw.text((1591, 184), "OmniMech", fill=colors["muted"], font=small_font)

    # C. Stopping semantics, separating agent choice from censoring.
    draw.text((76, 636), "C  Why trajectories stopped", fill=colors["ink"], font=panel_font)
    stop_order = [
        ("Strict pass", "strict_pass", colors["green"]),
        ("Agent stop", "agent_stop", colors["teal"]),
        ("Safety ceiling", "max_iterations", colors["orange"]),
        ("Runtime censor", "decision_unavailable", colors["red"]),
    ]
    maximum = max(1, max(trajectory_summary["stop_reasons"].values()))
    for index, (label, key, color) in enumerate(stop_order):
        value = int(trajectory_summary["stop_reasons"].get(key, 0))
        y = 714 + index * 66
        draw.text((104, y), label, fill=colors["ink"], font=body_font)
        draw.rectangle((280, y + 2, 760, y + 31), fill=colors["light"])
        draw.rectangle((280, y + 2, 280 + 480 * value / maximum, y + 31), fill=color)
        draw.text((774, y + 4), str(value), fill=colors["ink"], font=body_font)
    draw.text(
        (104, 990),
        "Agent stop is a model decision; safety/runtime censoring is reported separately.",
        fill=colors["muted"], font=small_font,
    )

    # D. Dataset stratification exposes the harder mechanical subset.
    draw.text((920, 636), "D  Dataset stratification", fill=colors["ink"], font=panel_font)
    datasets = trajectory_summary.get("by_dataset", [])
    chart_left, chart_right = 1185, 1670
    for tick in range(0, 101, 20):
        x = chart_left + (chart_right - chart_left) * tick / 100
        draw.line((x, 704, x, 940), fill=colors["grid"], width=1)
        draw.text((x - 10, 951), str(tick), fill=colors["muted"], font=small_font)
    for index, dataset in enumerate(datasets):
        name = dataset["dataset"]
        subset = [row for row in results if row["sample_id"].startswith(name + ":")]
        first_passes = sum(bool(row.get("attempts") and row["attempts"][0].get("passed")) for row in subset)
        first_rate = 100 * first_passes / max(1, len(subset))
        final_rate = float(dataset["strict_pass_rate"])
        y = 724 + index * 116
        draw.text((936, y + 22), f"{name}  n={len(subset)}", fill=colors["ink"], font=body_font)
        draw.rectangle((chart_left, y, chart_left + (chart_right - chart_left) * first_rate / 100, y + 28), fill=colors["gray"])
        draw.rectangle((chart_left, y + 39, chart_left + (chart_right - chart_left) * final_rate / 100, y + 67), fill=colors["teal"] if name == "ortho2cad" else colors["orange"])
        draw.text((chart_right + 12, y + 4), f"{first_rate:.1f}%", fill=colors["muted"], font=small_font)
        draw.text((chart_right + 12, y + 43), f"{final_rate:.1f}%", fill=colors["ink"], font=small_font)
    draw.rectangle((1185, 985, 1203, 1003), fill=colors["gray"])
    draw.text((1211, 984), "Pass@1", fill=colors["muted"], font=small_font)
    draw.rectangle((1290, 985, 1308, 1003), fill=colors["teal"])
    draw.text((1316, 984), "Final strict", fill=colors["muted"], font=small_font)

    draw.text(
        (76, 1060),
        "Selected checkpoint preserves the best scorable candidate. One v2 run was runtime-censored; v3 adds decision transport retries.",
        fill=colors["muted"], font=small_font,
    )
    return image


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
    render_agent_evaluation_figure(
        materialized["results"], summary, trajectory_summary,
    ).save(output_dir / "agent-evaluation.png")
    with (output_dir / "report.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n## Agent loop outcomes\n\n"
            "Fixed-model loop evaluation with autonomous stopping and separate safety/runtime "
            "censoring. The v2 campaign remains immutable; v3 adds decision transport retries "
            "after observing one censored reflection turn.\n\n"
            "![Agent loop evaluation](agent-evaluation.png)\n"
        )
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
        with (output_dir / "report.md").open("a", encoding="utf-8") as stream:
            count = comparison["paired_samples"]
            stream.write(
                "\n## Paired Agent comparison\n\n"
                "Same `gpt-5.6-sol` model, reasoning effort, frozen 30-sample selection, and "
                "strict verifier. This is a paired historical comparison, not a randomized A/B.\n\n"
                "| Metric | Baseline Agent | Native-feedback Agent | Delta |\n"
                "| --- | ---: | ---: | ---: |\n"
                f"| Strict final | {comparison['baseline_strict_passes']}/{count} | "
                f"{comparison['candidate_strict_passes']}/{count} | "
                f"{comparison['candidate_strict_passes'] - comparison['baseline_strict_passes']:+d} |\n"
                f"| Pass@1 | {comparison['baseline_pass_at_1']}/{count} | "
                f"{comparison['candidate_pass_at_1']}/{count} | "
                f"{comparison['candidate_pass_at_1'] - comparison['baseline_pass_at_1']:+d} |\n"
                f"| Selected mean | {comparison['baseline_selected_mean']:.2f} | "
                f"{comparison['candidate_selected_mean']:.2f} | "
                f"{comparison['mean_score_delta']:+.2f} |\n"
                f"| Mean attempts | {comparison['baseline_mean_attempts']:.2f} | "
                f"{comparison['candidate_mean_attempts']:.2f} | "
                f"{comparison['candidate_mean_attempts'] - comparison['baseline_mean_attempts']:+.2f} |\n\n"
                f"Paired strict-pass sign test: `p={comparison['paired_sign_test_p']}`. "
                "The complete per-sample table is `paired-sol-comparison.csv`.\n"
            )
    return {
        "summary": summary,
        "trajectory_summary": trajectory_summary,
        "comparison": comparison,
        "materialization": materialized["provenance"],
    }
