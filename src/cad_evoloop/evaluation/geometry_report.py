"""Generate paper-ready summaries and trajectory figures for geometry campaigns."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from PIL import Image, ImageDraw, ImageFont


COLORS = ("#15616D", "#E36414", "#4F46E5", "#2A9D8F", "#B42318", "#6B7280")


def _font(size: int, *, bold: bool = False):
    names = ("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _lighten(color: str, amount: float = 0.58) -> str:
    channels = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
    mixed = [round(value + (255 - value) * amount) for value in channels]
    return "#" + "".join(f"{value:02X}" for value in mixed)


def geometry_report_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        selected = result.get("selected_attempt_id")
        for attempt in result.get("attempts", []):
            rows.append({
                "sample_id": result["sample_id"],
                "model": result["model"],
                "attempt_id": attempt["attempt_id"],
                "attempt_number": attempt["attempt_number"],
                "score": float(attempt["score"]),
                "passed": bool(attempt["passed"]),
                "selected": attempt["attempt_id"] == selected,
                "agent_decision": attempt.get("agent_decision"),
                "can_improve": attempt.get("can_improve"),
                "stagnation_advisory": bool(attempt.get("stagnation_advisory")),
                "safety_stop_reason": attempt.get("safety_stop_reason"),
                "run_stop_reason": result.get("stop_reason"),
                "elapsed_seconds": float(attempt["elapsed_seconds"]),
                "timed_out": bool(attempt.get("timed_out")),
                "decision_transport_retries": int(
                    attempt.get("decision_transport_retries", 0) or 0
                ),
                "decision_recovered": bool(attempt.get("decision_recovered")),
                "codex_error_events": len(attempt.get("errors", [])),
                "input_tokens": int(attempt.get("usage", {}).get("input_tokens", 0) or 0),
                "cached_input_tokens": int(
                    attempt.get("usage", {}).get("cached_input_tokens", 0) or 0
                ),
                "output_tokens": int(attempt.get("usage", {}).get("output_tokens", 0) or 0),
                "reasoning_output_tokens": int(
                    attempt.get("usage", {}).get("reasoning_output_tokens", 0) or 0
                ),
            })
    return rows


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _mcp_audit_metrics(result: dict[str, Any]) -> dict[str, int]:
    metrics = {
        "mcp_tool_calls": 0,
        "mcp_failed_calls": 0,
        "core_job_failures": 0,
        "core_job_timeouts": 0,
    }
    job_dir = result.get("job_dir")
    if not job_dir:
        return metrics
    terminal_jobs: set[tuple[str, str]] = set()
    for attempt in result.get("attempts", []):
        audit_path = Path(job_dir) / "attempts" / attempt["attempt_id"] / "mcp-audit.jsonl"
        if not audit_path.is_file():
            continue
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "tool.call":
                continue
            metrics["mcp_tool_calls"] += 1
            if event.get("status") != "pass":
                metrics["mcp_failed_calls"] += 1
            if event.get("tool") != "autocad_core_status":
                continue
            content = event.get("response", {}).get("result", {}).get("content", [])
            for item in content:
                try:
                    payload = json.loads(item.get("text", ""))
                except (json.JSONDecodeError, AttributeError):
                    continue
                status = payload.get("status")
                job_id = payload.get("job_id")
                key = (str(job_id), str(status))
                if key in terminal_jobs:
                    continue
                terminal_jobs.add(key)
                if status in {"failed", "cancelled"}:
                    metrics["core_job_failures"] += 1
                elif status == "timed_out":
                    metrics["core_job_timeouts"] += 1
    return metrics


def _run_metrics(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts", [])
    usage_fields = (
        "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
    )
    metrics: dict[str, Any] = {
        "attempts": len(attempts),
        "elapsed_seconds": round(sum(float(item.get("elapsed_seconds", 0)) for item in attempts), 3),
        "timed_out_attempts": sum(bool(item.get("timed_out")) for item in attempts),
        "decision_transport_retries": sum(
            int(item.get("decision_transport_retries", 0) or 0) for item in attempts
        ),
        "recovered_decisions": sum(bool(item.get("decision_recovered")) for item in attempts),
        "codex_error_events": sum(len(item.get("errors", [])) for item in attempts),
        "verifier_errors": 0,
    }
    for field in usage_fields:
        metrics[field] = sum(
            int(item.get("usage", {}).get(field, 0) or 0) for item in attempts
        )
    for attempt in attempts:
        verdict = _read_json(attempt.get("verdict"))
        metrics["verifier_errors"] += bool(
            verdict and verdict.get("error_type") == "geometry-verifier-error"
        )
    metrics.update(_mcp_audit_metrics(result))
    return metrics


def summarize_models(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    models = list(dict.fromkeys(result["model"] for result in results))
    summaries = []
    for model in models:
        model_results = [result for result in results if result["model"] == model]
        run_metrics = [_run_metrics(result) for result in model_results]
        first_scores = [
            float(result["attempts"][0]["score"])
            for result in model_results if result.get("attempts")
        ]
        selected_scores = [float(result["score"]) for result in model_results]
        recovery_gains = [
            float(result["score"]) - float(result["attempts"][0]["score"])
            for result in model_results if result.get("attempts")
        ]
        first_passes = sum(
            bool(result["attempts"][0]["passed"])
            for result in model_results if result.get("attempts")
        )
        strict_passes = sum(bool(result["passed"]) for result in model_results)
        runs = len(model_results)
        attempts = sum(item["attempts"] for item in run_metrics)
        elapsed = sum(item["elapsed_seconds"] for item in run_metrics)
        summaries.append({
            "model": model,
            "runs": runs,
            "pass_at_1": first_passes,
            "pass_at_1_rate": round(100 * first_passes / runs, 2) if runs else 0.0,
            "strict_passes": strict_passes,
            "strict_pass_rate": round(100 * strict_passes / runs, 2) if runs else 0.0,
            "first_attempt_mean": _mean(first_scores),
            "selected_mean": _mean(selected_scores),
            "mean_recovery_gain": _mean(recovery_gains),
            "runs_improved": sum(
                float(result["score"]) > float(result["attempts"][0]["score"])
                for result in model_results if result.get("attempts")
            ),
            "attempts": attempts,
            "mean_attempts": round(attempts / runs, 2) if runs else 0.0,
            "total_elapsed_seconds": round(elapsed, 2),
            "mean_elapsed_seconds": round(elapsed / runs, 2) if runs else 0.0,
            **{
                field: sum(int(item[field]) for item in run_metrics)
                for field in (
                    "input_tokens", "cached_input_tokens", "output_tokens",
                    "reasoning_output_tokens", "timed_out_attempts", "codex_error_events",
                    "decision_transport_retries", "recovered_decisions", "verifier_errors",
                    "mcp_tool_calls", "mcp_failed_calls",
                    "core_job_failures", "core_job_timeouts",
                )
            },
            "integrity_passes": sum(
                bool(result.get("integrity", {}).get("ok")) for result in model_results
            ),
        })
    return summaries


def summarize_geometry_campaign(manifest: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    first_scores = [float(result["attempts"][0]["score"]) for result in results if result.get("attempts")]
    best_scores = [float(result["score"]) for result in results]
    recovery_gains = [
        float(result["score"]) - float(result["attempts"][0]["score"])
        for result in results if result.get("attempts")
    ]
    first_passes = sum(
        bool(result["attempts"][0]["passed"])
        for result in results if result.get("attempts")
    )
    by_model = summarize_models(results)
    return {
        "campaign_id": manifest["campaign_id"],
        "protocol": manifest["protocol"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "benchmark_split": manifest.get("benchmark_split"),
        "execution": manifest.get("execution"),
        "runs": len(results),
        "pass_at_1": first_passes,
        "pass_at_1_rate": round(100 * first_passes / len(results), 2) if results else 0.0,
        "strict_passes": sum(bool(result["passed"]) for result in results),
        "strict_pass_rate": round(
            100 * sum(bool(result["passed"]) for result in results) / len(results), 2,
        ) if results else 0.0,
        "attempts": sum(len(result.get("attempts", [])) for result in results),
        "first_attempt_mean": _mean(first_scores),
        "selected_mean": _mean(best_scores),
        "mean_recovery_gain": _mean(recovery_gains),
        "runs_improved": sum(
            float(result["score"]) > float(result["attempts"][0]["score"])
            for result in results if result.get("attempts")
        ),
        "integrity_passes": sum(bool(result.get("integrity", {}).get("ok")) for result in results),
        "total_elapsed_seconds": round(sum(
            float(model["total_elapsed_seconds"]) for model in by_model
        ), 2),
        "input_tokens": sum(int(model["input_tokens"]) for model in by_model),
        "output_tokens": sum(int(model["output_tokens"]) for model in by_model),
        "by_model": by_model,
    }


def render_geometry_trajectories(
    manifest: dict[str, Any],
    results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Image.Image:
    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    heading_font = _font(21, bold=True)
    body_font = _font(17)
    small_font = _font(14)
    draw.text((78, 42), "EvoCAD Geometry Repair Trajectories", fill="#171717", font=title_font)
    recovery = summary["mean_recovery_gain"]
    recovery_label = f"{recovery:+.2f}" if recovery is not None else "n/a"
    subtitle = (
        f"{summary['campaign_id']}  |  {summary['protocol']}  |  "
        f"strict {summary['strict_passes']}/{summary['runs']}  |  "
        f"mean recovery {recovery_label}"
    )
    draw.text((80, 91), subtitle, fill="#4B5563", font=body_font)

    left, top, right, bottom = 105, 165, 1165, 790
    plot_width, plot_height = right - left, bottom - top
    max_attempts = max((len(result.get("attempts", [])) for result in results), default=1)
    max_attempts = max(max_attempts, 2)
    for tick in range(0, 101, 20):
        y = bottom - plot_height * tick / 100
        draw.line((left, y, right, y), fill="#E5E7EB", width=2)
        label = str(tick)
        box = draw.textbbox((0, 0), label, font=small_font)
        draw.text((left - 16 - (box[2] - box[0]), y - 8), label, fill="#4B5563", font=small_font)
    for attempt in range(1, max_attempts + 1):
        x = left + plot_width * (attempt - 1) / (max_attempts - 1)
        draw.line((x, top, x, bottom), fill="#F3F4F6", width=1)
        draw.text((x - 4, bottom + 18), str(attempt), fill="#4B5563", font=small_font)
    draw.line((left, top, left, bottom), fill="#374151", width=2)
    draw.line((left, bottom, right, bottom), fill="#374151", width=2)
    draw.text((left + plot_width // 2 - 62, 838), "Repair attempt", fill="#374151", font=body_font)
    draw.text((20, top + plot_height // 2), "Score", fill="#374151", font=body_font)
    draw.text((right - 132, top - 26), "strict target", fill="#B42318", font=small_font)
    draw.line((right - 10, top, right, top), fill="#B42318", width=4)

    detailed = len(results) <= 8
    models = list(dict.fromkeys(result["model"] for result in results))
    model_colors = {model: COLORS[index % len(COLORS)] for index, model in enumerate(models)}
    legend_y = 172
    for index, result in enumerate(results):
        attempts = result.get("attempts", [])
        if not attempts:
            continue
        color = model_colors[result["model"]] if not detailed else COLORS[index % len(COLORS)]
        line_color = color if detailed else _lighten(color)
        points = []
        for attempt in attempts:
            x = left + plot_width * (int(attempt["attempt_number"]) - 1) / (max_attempts - 1)
            y = bottom - plot_height * float(attempt["score"]) / 100
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=line_color, width=5 if detailed else 2, joint="curve")
        for attempt, (x, y) in zip(attempts, points):
            selected = attempt["attempt_id"] == result.get("selected_attempt_id")
            if not detailed and not selected:
                continue
            radius = 10 if selected and detailed else 5 if selected else 7
            fill = "#17803D" if attempt["passed"] else color
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline="#FFFFFF", width=2)
            if detailed:
                draw.text((x + 11, y - 25), f"{float(attempt['score']):.1f}", fill="#303030", font=small_font)
        if detailed:
            label = f"{result['sample_id']} / {result['model']}"
            draw.line((1230, legend_y + 9, 1264, legend_y + 9), fill=color, width=5)
            draw.text((1276, legend_y), label[:34], fill="#242424", font=small_font)
            trajectory = " -> ".join(f"{float(item['score']):.1f}" for item in attempts)
            draw.text((1230, legend_y + 25), trajectory, fill="#6B7280", font=small_font)
            legend_y += 62

    if not detailed:
        for model in models[:9]:
            model_results = [result for result in results if result["model"] == model]
            selected_mean = statistics.mean(float(result["score"]) for result in model_results)
            color = model_colors[model]
            draw.line((1230, legend_y + 9, 1264, legend_y + 9), fill=color, width=5)
            draw.text((1276, legend_y), model[:30], fill="#242424", font=small_font)
            draw.text(
                (1230, legend_y + 25),
                f"n={len(model_results)}  selected mean={selected_mean:.1f}",
                fill="#6B7280",
                font=small_font,
            )
            legend_y += 62
        if len(models) > 9:
            draw.text((1230, legend_y), f"+ {len(models) - 9} more models", fill="#6B7280", font=small_font)

    draw.text((1218, 125), "Runs", fill="#171717", font=heading_font)
    mode_label = "individual runs" if detailed else "runs grouped by model"
    footer = (
        f"Manifest {manifest['manifest_sha256'][:16]}...  |  Green marker = strict pass  |  "
        f"Selected checkpoint marker  |  {mode_label}"
    )
    draw.text((80, 870), footer, fill="#6B7280", font=small_font)
    return image


def render_model_comparison(summary: dict[str, Any]) -> Image.Image:
    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    heading_font = _font(20, bold=True)
    body_font = _font(17)
    small_font = _font(14)
    draw.text((78, 42), "EvoCAD Model Cost and Reliability", fill="#171717", font=title_font)
    draw.text(
        (80, 91),
        f"{summary['campaign_id']}  |  strict geometry protocol  |  n={summary['runs']}",
        fill="#4B5563",
        font=body_font,
    )
    panels = [
        ("Strict pass rate", "pass_at_1_rate", "strict_pass_rate", "Pass@1", "After repair", "%"),
        ("Geometry score", "first_attempt_mean", "selected_mean", "First", "Selected", ""),
    ]
    all_models = summary["by_model"]
    models = all_models[:3]
    chart_left, chart_right = 285, 1115
    panel_tops = (190, 465)
    bar_height = 23
    for panel_top, (title, first_key, second_key, first_label, second_label, suffix) in zip(
        panel_tops, panels,
    ):
        draw.text((80, panel_top - 42), title, fill="#171717", font=heading_font)
        for tick in range(0, 101, 20):
            x = chart_left + (chart_right - chart_left) * tick / 100
            draw.line((x, panel_top - 8, x, panel_top + 188), fill="#E5E7EB", width=1)
            draw.text((x - 8, panel_top + 197), str(tick), fill="#6B7280", font=small_font)
        for index, model in enumerate(models):
            y = panel_top + index * 62
            draw.text((80, y + 12), model["model"][:23], fill="#242424", font=small_font)
            for offset, key, color in ((0, first_key, "#9CA3AF"), (bar_height + 4, second_key, COLORS[index % len(COLORS)])):
                value = float(model[key] or 0)
                draw.rectangle(
                    (chart_left, y + offset, chart_left + (chart_right - chart_left) * value / 100, y + offset + bar_height),
                    fill=color,
                )
                draw.text(
                    (chart_right + 14, y + offset + 2), f"{value:.1f}{suffix}",
                    fill="#374151", font=small_font,
                )
        legend_y = panel_top - 41
        draw.rectangle((840, legend_y, 858, legend_y + 18), fill="#9CA3AF")
        draw.text((866, legend_y), first_label, fill="#4B5563", font=small_font)
        draw.rectangle((955, legend_y, 973, legend_y + 18), fill=COLORS[0])
        draw.text((981, legend_y), second_label, fill="#4B5563", font=small_font)

    info_x = 1215
    draw.text((info_x, 150), "Efficiency", fill="#171717", font=heading_font)
    for index, model in enumerate(models):
        y = 205 + index * 185
        draw.line((info_x, y - 18, 1515, y - 18), fill="#E5E7EB", width=1)
        draw.text((info_x, y), model["model"][:26], fill=COLORS[index % len(COLORS)], font=heading_font)
        details = [
            f"{model['mean_attempts']:.2f} attempts/run",
            f"{model['mean_elapsed_seconds'] / 60:.1f} min/run",
            f"{model['output_tokens'] / max(model['runs'], 1) / 1000:.1f}k output tok/run",
            f"{model['timed_out_attempts']} agent timeouts",
            f"{model['decision_transport_retries']} decision retries / "
            f"{model['recovered_decisions']} recovered",
            f"{model['mcp_failed_calls']} MCP / {model['core_job_failures']} core failures",
        ]
        for line_index, line in enumerate(details):
            draw.text((info_x, y + 35 + line_index * 25), line, fill="#4B5563", font=small_font)
    draw.text(
        (80, 870),
        "Selected checkpoints survive regressions; failure counts are diagnostic events and may recover within a run."
        + (f"  {len(all_models) - 3} additional models: see models.csv." if len(all_models) > 3 else ""),
        fill="#6B7280",
        font=small_font,
    )
    return image


def _load_data_quality(
    annotations_path: str | Path,
    manifest: dict[str, Any],
    results: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(annotations_path).resolve()
    annotations = json.loads(path.read_text(encoding="utf-8"))
    if annotations.get("schema_version") != "1.0":
        raise ValueError(f"Unsupported data-quality annotations: {path}")
    if annotations.get("campaign_manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("Data-quality annotations target a different campaign manifest")
    samples = annotations.get("samples", {})
    result_ids = {result["sample_id"] for result in results}
    unknown = set(samples) - result_ids
    if unknown:
        raise ValueError(f"Data-quality annotations contain unknown samples: {sorted(unknown)}")
    excluded = sorted(
        sample_id for sample_id, value in samples.items()
        if value.get("status") == "exclude_primary"
    )
    primary_results = [result for result in results if result["sample_id"] not in excluded]
    quality = {
        "annotations_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "annotated_samples": len(samples),
        "excluded_sample_ids": excluded,
        "review_sample_ids": sorted(
            sample_id for sample_id, value in samples.items()
            if value.get("status") == "review"
        ),
    }
    return quality, primary_results


def generate_geometry_campaign_report(
    campaign_dir: str | Path,
    output_dir: str | Path,
    annotations_path: str | Path | None = None,
) -> dict[str, Any]:
    campaign_dir = Path(campaign_dir).resolve()
    output_dir = Path(output_dir).resolve()
    manifest = json.loads((campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8"))
    results = json.loads((campaign_dir / "results.json").read_text(encoding="utf-8"))
    summary = summarize_geometry_campaign(manifest, results)
    primary_summary = None
    if annotations_path is not None:
        quality, primary_results = _load_data_quality(annotations_path, manifest, results)
        primary_summary = summarize_geometry_campaign(manifest, primary_results)
        quality["primary"] = {
            key: primary_summary[key]
            for key in (
                "runs", "pass_at_1", "pass_at_1_rate", "strict_passes",
                "strict_pass_rate", "attempts", "first_attempt_mean", "selected_mean",
                "mean_recovery_gain", "total_elapsed_seconds", "by_model",
            )
        }
        summary["data_quality"] = quality
    rows = geometry_report_rows(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8",
    )
    with (output_dir / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        fieldnames = list(rows[0]) if rows else [
            "sample_id", "model", "attempt_id", "attempt_number", "score", "passed",
            "selected", "agent_decision", "can_improve", "stagnation_advisory",
            "safety_stop_reason", "run_stop_reason", "elapsed_seconds", "timed_out",
            "decision_transport_retries", "decision_recovered", "codex_error_events",
            "input_tokens",
            "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    model_rows = summary["by_model"]
    with (output_dir / "models.csv").open("w", newline="", encoding="utf-8") as stream:
        fieldnames = list(model_rows[0]) if model_rows else ["model", "runs"]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(model_rows)
    if primary_summary is not None:
        primary_model_rows = primary_summary["by_model"]
        with (output_dir / "models-primary.csv").open(
            "w", newline="", encoding="utf-8",
        ) as stream:
            fieldnames = (
                list(primary_model_rows[0]) if primary_model_rows else ["model", "runs"]
            )
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(primary_model_rows)
    render_geometry_trajectories(manifest, results, summary).save(
        output_dir / "repair-trajectories.png",
    )
    render_model_comparison(summary).save(output_dir / "model-comparison.png")
    if primary_summary is not None:
        render_model_comparison(primary_summary).save(
            output_dir / "model-comparison-primary.png"
        )
    model_lines = [
        "| Model | Pass@1 | Strict final | First mean | Selected mean | Attempts/run | Min/run | MCP failures | Core failures |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in model_rows:
        model_lines.append(
            f"| {model['model']} | {model['pass_at_1_rate']:.2f}% | "
            f"{model['strict_pass_rate']:.2f}% | {model['first_attempt_mean']} | "
            f"{model['selected_mean']} | {model['mean_attempts']:.2f} | "
            f"{model['mean_elapsed_seconds'] / 60:.2f} | {model['mcp_failed_calls']} | "
            f"{model['core_job_failures']} |"
        )
    quality_lines = []
    if primary_summary is not None:
        quality_lines = [
            "## Data-quality-filtered primary result",
            "",
            f"Excluded samples: {', '.join(summary['data_quality']['excluded_sample_ids']) or 'none'}.",
            f"Primary runs: {primary_summary['runs']}; strict passes: "
            f"{primary_summary['strict_passes']} ({primary_summary['strict_pass_rate']:.2f}%); "
            f"pass@1: {primary_summary['pass_at_1']} "
            f"({primary_summary['pass_at_1_rate']:.2f}%).",
            "",
            "![Primary model cost and reliability](model-comparison-primary.png)",
            "",
        ]
    report = "\n".join([
        f"# Geometry Campaign: {summary['campaign_id']}",
        "",
        f"Protocol: `{summary['protocol']}`; manifest: `{summary['manifest_sha256']}`.",
        "",
        f"Runs: {summary['runs']}; strict passes: {summary['strict_passes']} "
        f"({summary['strict_pass_rate']:.2f}%); pass@1: {summary['pass_at_1']} "
        f"({summary['pass_at_1_rate']:.2f}%); attempts: {summary['attempts']}.",
        f"First-attempt mean: {summary['first_attempt_mean']}; selected mean: "
        f"{summary['selected_mean']}; recovery gain: {summary['mean_recovery_gain']}.",
        "Failure counters are diagnostic events, not failed runs; later retries may recover "
        "within the same agent attempt.",
        "",
        *quality_lines,
        "## Model comparison",
        "",
        *model_lines,
        "",
        "![Model cost and reliability](model-comparison.png)",
        "",
        "## Repair trajectories",
        "",
        "![Geometry repair trajectories](repair-trajectories.png)",
        "",
    ])
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary
