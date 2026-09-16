"""Post-hoc BenchCAD trajectory scoring and reproducible campaign statistics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any

from cad_evoloop.evaluation.benchcad_campaign import _run_bridge
from cad_evoloop.paths import project_root


OPENAI_SOL_NO_TOOLS = 0.706
OPENAI_SOL_PYTHON_TOOL = 0.834
OPENAI_SOL_SOURCE = "https://openai.com/index/gpt-5-6/"


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bootstrap_mean_ci(
    values: list[float], *, samples: int = 10_000, seed: int = 56,
) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    size = len(values)
    means = [sum(values[rng.randrange(size)] for _ in range(size)) / size for _ in range(samples)]
    return [round(_percentile(means, 0.025), 6), round(_percentile(means, 0.975), 6)]


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.mean(left), statistics.mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_norm = sum((x - left_mean) ** 2 for x in left)
    right_norm = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_norm * right_norm)
    return round(numerator / denominator, 6) if denominator else None


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average = (cursor + 1 + end) / 2
        for position in range(cursor, end):
            ranks[indexed[position][0]] = average
        cursor = end
    return ranks


def _describe(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6) if values else None,
        "median": round(statistics.median(values), 6) if values else None,
        "sample_stddev": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
        "bootstrap_95_ci": _bootstrap_mean_ci(values),
        "minimum": round(min(values), 6) if values else None,
        "maximum": round(max(values), 6) if values else None,
    }


def summarize_checkpoint_scores(cases: list[dict[str, Any]], max_iterations: int) -> dict[str, Any]:
    final_scores = [float(case["final_iou"]) for case in cases]
    first_scores = [float(case["first_iou"]) for case in cases]
    best_scores = [float(case["best_iou"]) for case in cases]
    image_scores = [float(case["final_image_iou"]) for case in cases]
    uplift = [final - first for final, first in zip(final_scores, first_scores)]
    regret = [best - final for best, final in zip(best_scores, final_scores)]
    difficulties = sorted({str(case.get("difficulty") or "unknown") for case in cases})
    by_difficulty = {}
    for difficulty in difficulties:
        rows = [case for case in cases if str(case.get("difficulty") or "unknown") == difficulty]
        by_difficulty[difficulty] = {
            "official_iou": _describe([float(row["final_iou"]) for row in rows]),
            "mean_iterations": round(statistics.mean(float(row["iterations"]) for row in rows), 3),
        }
    return {
        "official_iou": _describe(final_scores),
        "first_checkpoint_iou": _describe(first_scores),
        "oracle_best_checkpoint_iou": _describe(best_scores),
        "loop_uplift": {
            **_describe(uplift),
            "improved": sum(value > 1e-9 for value in uplift),
            "tied": sum(abs(value) <= 1e-9 for value in uplift),
            "regressed": sum(value < -1e-9 for value in uplift),
        },
        "selection_regret": {
            **_describe(regret),
            "selected_oracle_best": sum(value <= 1e-9 for value in regret),
        },
        "execution": {
            "records": len(cases),
            "scored": len(final_scores),
            "submission_rate": round(len(final_scores) / len(cases), 6) if cases else 0.0,
            "candidate_checkpoints": sum(case["iterations"] for case in cases),
            "mean_iterations": round(statistics.mean(case["iterations"] for case in cases), 3) if cases else 0.0,
            "median_iterations": statistics.median(case["iterations"] for case in cases) if cases else 0.0,
            "safety_ceiling_reached": sum(case["iterations"] >= max_iterations for case in cases),
            "summed_record_elapsed_seconds": round(sum(case.get("elapsed_seconds", 0) for case in cases), 3),
            "trajectory_usage_scope": "action and decision turns; excludes IR builder",
            "recorded_input_tokens": sum(case.get("input_tokens", 0) for case in cases),
            "recorded_cached_input_tokens": sum(case.get("cached_input_tokens", 0) for case in cases),
            "recorded_output_tokens": sum(case.get("output_tokens", 0) for case in cases),
            "recorded_reasoning_output_tokens": sum(case.get("reasoning_output_tokens", 0) for case in cases),
        },
        "threshold_rates": {
            f"iou_at_least_{threshold:.2f}": round(sum(value >= threshold for value in final_scores) / len(final_scores), 6)
            for threshold in (0.50, 0.70, 0.80, 0.90, 0.95)
        },
        "proxy_alignment": {
            "final_image_iou": _describe(image_scores),
            "pearson_r": _pearson(image_scores, final_scores),
            "spearman_rho": _pearson(_rank(image_scores), _rank(final_scores)),
        },
        "by_difficulty": by_difficulty,
    }


def _load_records(data_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        row["record_id"]: row
        for row in (
            json.loads(line)
            for line in (data_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _score_checkpoint(
    python: Path, upstream: Path, data_dir: Path, record: dict[str, Any], attempt: Path,
    resolution: int, timeout: int,
) -> dict[str, Any]:
    return _run_bridge(
        python,
        [
            "--upstream", str(upstream), "score",
            "--code", str(attempt / "candidate.py"),
            "--step", str(attempt / "candidate.step"),
            "--gt-code", str(data_dir / record["code_path"]),
            "--gt-step", str(data_dir / record["step_path"]),
            "--family", record["family"],
            "--resolution", str(resolution),
        ],
        timeout,
    )


def _write_posthoc(path: Path, record_id: str, scores: dict[int, dict[str, Any]]) -> None:
    payload = {
        "protocol": "evocad-benchcad-posthoc-v1",
        "record_id": record_id,
        "not_fed_to_agent": True,
        "purpose": "evaluator-only checkpoint attribution",
        "attempts": [
            {"iteration": iteration, "official": scores[iteration]}
            for iteration in sorted(scores)
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _markdown(analysis: dict[str, Any]) -> str:
    score = analysis["statistics"]["official_iou"]
    uplift = analysis["statistics"]["loop_uplift"]
    regret = analysis["statistics"]["selection_regret"]
    execution = analysis["statistics"]["execution"]
    comparison = analysis["public_comparison"]
    lines = [
        "# EvoCAD BenchCAD Sol family-diverse pilot",
        "",
        "## Primary result",
        "",
        f"- Records scored: {execution['scored']}/{execution['records']}",
        f"- Mean official 64-cubed voxel IoU: {score['mean']:.6f}",
        f"- Bootstrap 95% CI: [{score['bootstrap_95_ci'][0]:.6f}, {score['bootstrap_95_ci'][1]:.6f}]",
        f"- Median IoU: {score['median']:.6f}",
        f"- Mean iterations: {execution['mean_iterations']:.3f}",
        f"- Safety ceiling reached: {execution['safety_ceiling_reached']}",
        "",
        "## Loop attribution",
        "",
        f"- First-checkpoint mean IoU: {analysis['statistics']['first_checkpoint_iou']['mean']:.6f}",
        f"- Final-minus-first mean: {uplift['mean']:.6f}",
        f"- Paired bootstrap 95% CI: [{uplift['bootstrap_95_ci'][0]:.6f}, {uplift['bootstrap_95_ci'][1]:.6f}]",
        f"- Improved / tied / regressed: {uplift['improved']} / {uplift['tied']} / {uplift['regressed']}",
        f"- Oracle-best checkpoint mean: {analysis['statistics']['oracle_best_checkpoint_iou']['mean']:.6f}",
        f"- Mean final-selection regret: {regret['mean']:.6f}",
        "",
        "## Public comparison",
        "",
        f"OpenAI reports Sol at {comparison['sol_no_tools']:.3f} without tools and "
        f"{comparison['sol_python_tool']:.3f} with a Python tool. EvoCAD's descriptive delta "
        f"to the published tool score is {comparison['delta_to_sol_python_tool']:+.6f}.",
        "",
        "This is not an apples-to-apples leaderboard comparison: the public split/attempt metadata, "
        "outer-loop semantics, reasoning setting, and process isolation differ. The campaign is a "
        "fixed 30-family local audited pilot, not an official BenchCAD submission.",
        "",
        f"Source: {comparison['source']}",
        "",
        "All checkpoint scores are post-hoc evaluator-only measurements and were never fed back to the Agent.",
    ]
    return "\n".join(lines) + "\n"


def _write_figures(cases: list[dict[str, Any]], output: Path) -> list[str]:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "bold",
        "figure.facecolor": "white",
        "axes.facecolor": "#fafafa",
    })
    artifacts: list[str] = []

    ordered = sorted(cases, key=lambda row: row["final_iou"] - row["first_iou"])
    fig, ax = plt.subplots(figsize=(9.2, 10.5), constrained_layout=True)
    for index, row in enumerate(ordered):
        improved = row["final_iou"] >= row["first_iou"]
        color = "#198754" if improved else "#d1495b"
        ax.plot([row["first_iou"], row["final_iou"]], [index, index], color=color, alpha=0.72, linewidth=2)
        ax.scatter(row["first_iou"], index, facecolors="white", edgecolors="#3b4652", s=34, zorder=3)
        ax.scatter(row["final_iou"], index, color=color, s=38, zorder=3)
    ax.axvline(OPENAI_SOL_NO_TOOLS, color="#2878b5", linestyle="--", linewidth=1.2, label="Published Sol, no tools")
    ax.axvline(OPENAI_SOL_PYTHON_TOOL, color="#7a5195", linestyle=":", linewidth=1.6, label="Published Sol, Python tool")
    ax.set_yticks(range(len(ordered)), [row["family"] for row in ordered])
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("Official 64^3 voxel IoU")
    ax.set_title("EvoCAD feedback loop: first checkpoint to submitted result")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.045), ncol=2, frameon=False)
    ax.grid(axis="x", color="#d8dde3", linewidth=0.7)
    loop_path = output / "loop-uplift.png"
    fig.savefig(loop_path, dpi=220)
    fig.savefig(output / "loop-uplift.pdf")
    plt.close(fig)
    artifacts.extend([loop_path.name, "loop-uplift.pdf"])

    colors = {"easy": "#198754", "medium": "#e09f3e", "hard": "#6f42c1", "unknown": "#66707a"}
    fig, ax = plt.subplots(figsize=(7.4, 6.4), constrained_layout=True)
    for difficulty in ("easy", "medium", "hard", "unknown"):
        rows = [row for row in cases if (row.get("difficulty") or "unknown") == difficulty]
        if not rows:
            continue
        ax.scatter(
            [row["final_image_iou"] for row in rows], [row["final_iou"] for row in rows],
            s=58, alpha=0.82, color=colors[difficulty], label=f"{difficulty} (n={len(rows)})",
            edgecolors="white", linewidths=0.7,
        )
    for row in cases:
        if row["final_image_iou"] - row["final_iou"] > 0.25:
            ax.annotate(
                row["family"], (row["final_image_iou"], row["final_iou"]),
                xytext=(5, -9), textcoords="offset points", fontsize=8,
            )
    ax.plot([0, 1], [0, 1], color="#70777f", linewidth=1, linestyle="--", alpha=0.7)
    ax.axhline(OPENAI_SOL_PYTHON_TOOL, color="#7a5195", linewidth=1.2, linestyle=":")
    ax.set_xlim(0.2, 1.02)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Online image-only silhouette IoU")
    ax.set_ylabel("Hidden official 64^3 voxel IoU")
    ax.set_title("Image verifier is correlated, but misses hidden volume errors")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(color="#d8dde3", linewidth=0.7)
    proxy_path = output / "proxy-vs-official.png"
    fig.savefig(proxy_path, dpi=220)
    fig.savefig(output / "proxy-vs-official.pdf")
    plt.close(fig)
    artifacts.extend([proxy_path.name, "proxy-vs-official.pdf"])

    regret_rows = sorted(cases, key=lambda row: row["best_minus_final"], reverse=True)[:10]
    fig, ax = plt.subplots(figsize=(8.2, 5.4), constrained_layout=True)
    ax.barh(
        [row["family"] for row in reversed(regret_rows)],
        [row["best_minus_final"] for row in reversed(regret_rows)],
        color=["#d1495b" if row["best_minus_final"] > 0.05 else "#e09f3e" for row in reversed(regret_rows)],
    )
    ax.set_xlabel("Oracle-best IoU minus submitted IoU")
    ax.set_title("Checkpoint-selection regret isolates stopper/verifier failures")
    ax.grid(axis="x", color="#d8dde3", linewidth=0.7)
    regret_path = output / "selection-regret.png"
    fig.savefig(regret_path, dpi=220)
    fig.savefig(output / "selection-regret.pdf")
    plt.close(fig)
    artifacts.extend([regret_path.name, "selection-regret.pdf"])
    return artifacts


def generate_benchcad_report(
    campaign_dir: Path, data_dir: Path, upstream: Path, *, workers: int = 4,
    resolution: int = 64, timeout: int = 900,
) -> dict[str, Any]:
    campaign_dir = campaign_dir.resolve()
    data_dir = data_dir.resolve()
    upstream = upstream.resolve()
    python = upstream / ".venv/Scripts/python.exe"
    records = _load_records(data_dir)
    result_paths = sorted(campaign_dir.glob("*/result.json"))
    if not result_paths:
        raise FileNotFoundError(f"No BenchCAD results found under {campaign_dir}")

    cached: dict[str, dict[int, dict[str, Any]]] = {}
    pending: list[tuple[str, dict[str, Any], Path, int]] = []
    for result_path in result_paths:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        record_id = result["record_id"]
        cache_path = result_path.parent / "posthoc-official.json"
        scores: dict[int, dict[str, Any]] = {}
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            scores = {int(row["iteration"]): row["official"] for row in payload.get("attempts", [])}
        cached[record_id] = scores
        for attempt in sorted((result_path.parent / "attempts").glob("attempt-*")):
            iteration = int(attempt.name.rsplit("-", 1)[-1])
            if (
                (iteration not in scores or not scores[iteration].get("ok"))
                and (attempt / "candidate.py").is_file()
                and (attempt / "candidate.step").is_file()
            ):
                pending.append((record_id, records[record_id], attempt, iteration))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _score_checkpoint, python, upstream, data_dir, record, attempt, resolution, timeout,
            ): (record_id, iteration)
            for record_id, record, attempt, iteration in pending
        }
        for future in as_completed(futures):
            record_id, iteration = futures[future]
            cached[record_id][iteration] = future.result()
            _write_posthoc(campaign_dir / record_id / "posthoc-official.json", record_id, cached[record_id])

    cases: list[dict[str, Any]] = []
    for result_path in result_paths:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        record_id = result["record_id"]
        valid = {
            iteration: score for iteration, score in cached[record_id].items() if score.get("ok")
        }
        if not valid:
            raise RuntimeError(f"No valid checkpoint scores for {record_id}")
        final_iteration = int(result["iterations"])
        first_iteration = min(valid)
        best_iteration = max(valid, key=lambda iteration: (valid[iteration]["iou"], -iteration))
        final_score = result["official"]
        if abs(float(valid[final_iteration]["iou"]) - float(final_score["iou"])) > 1e-6:
            raise RuntimeError(f"Post-hoc final score mismatch for {record_id}")
        trajectory = result["trajectory"]
        usages = [
            usage
            for turn in trajectory
            for usage in (turn.get("action_usage") or {}, turn.get("decision_usage") or {})
        ]
        cases.append({
            "record_id": record_id,
            "family": result["family"],
            "difficulty": result.get("difficulty"),
            "iterations": final_iteration,
            "first_iou": float(valid[first_iteration]["iou"]),
            "final_iou": float(final_score["iou"]),
            "best_iou": float(valid[best_iteration]["iou"]),
            "best_iteration": best_iteration,
            "first_image_iou": float(trajectory[first_iteration - 1]["image_verdict"]["silhouette_iou"]),
            "final_image_iou": float(trajectory[final_iteration - 1]["image_verdict"]["silhouette_iou"]),
            "final_minus_first": round(float(final_score["iou"]) - float(valid[first_iteration]["iou"]), 6),
            "best_minus_final": round(float(valid[best_iteration]["iou"]) - float(final_score["iou"]), 6),
            "safety_ceiling_reached": final_iteration >= int(
                json.loads((campaign_dir / "summary.json").read_text(encoding="utf-8"))["config"]["max_iterations"]
            ),
            "elapsed_seconds": float(result.get("elapsed_seconds") or 0),
            "input_tokens": sum(int(usage.get("input_tokens") or 0) for usage in usages),
            "cached_input_tokens": sum(int(usage.get("cached_input_tokens") or 0) for usage in usages),
            "output_tokens": sum(int(usage.get("output_tokens") or 0) for usage in usages),
            "reasoning_output_tokens": sum(int(usage.get("reasoning_output_tokens") or 0) for usage in usages),
        })

    summary = json.loads((campaign_dir / "summary.json").read_text(encoding="utf-8"))
    statistics_payload = summarize_checkpoint_scores(cases, int(summary["config"]["max_iterations"]))
    mean_iou = statistics_payload["official_iou"]["mean"]
    analysis = {
        "protocol": "evocad-benchcad-analysis-v1",
        "campaign": summary["campaign"],
        "posthoc_gt_scores_fed_to_agent": False,
        "statistics": statistics_payload,
        "public_comparison": {
            "sol_no_tools": OPENAI_SOL_NO_TOOLS,
            "sol_python_tool": OPENAI_SOL_PYTHON_TOOL,
            "delta_to_sol_no_tools": round(mean_iou - OPENAI_SOL_NO_TOOLS, 6),
            "delta_to_sol_python_tool": round(mean_iou - OPENAI_SOL_PYTHON_TOOL, 6),
            "source": OPENAI_SOL_SOURCE,
            "directly_comparable": False,
            "limitations": [
                "family-diverse 30-record pilot rather than a confirmed identical official split",
                "EvoCAD outer iterations are not equivalent to vendor Python-tool calls",
                "medium reasoning and local audited process rather than confirmed vendor settings and Docker",
            ],
        },
        "cases": cases,
    }
    analysis["artifacts"] = _write_figures(cases, campaign_dir)
    (campaign_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    with (campaign_dir / "cases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(cases[0]))
        writer.writeheader()
        writer.writerows(cases)
    (campaign_dir / "summary.md").write_text(_markdown(analysis), encoding="utf-8", newline="\n")
    return analysis
