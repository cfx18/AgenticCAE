"""Generate paper-ready summaries and trajectory figures for geometry campaigns."""

from __future__ import annotations

import csv
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
                "elapsed_seconds": float(attempt["elapsed_seconds"]),
                "input_tokens": int(attempt.get("usage", {}).get("input_tokens", 0) or 0),
                "output_tokens": int(attempt.get("usage", {}).get("output_tokens", 0) or 0),
            })
    return rows


def summarize_geometry_campaign(manifest: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    first_scores = [float(result["attempts"][0]["score"]) for result in results if result.get("attempts")]
    best_scores = [float(result["score"]) for result in results]
    return {
        "campaign_id": manifest["campaign_id"],
        "protocol": manifest["protocol"],
        "manifest_sha256": manifest["manifest_sha256"],
        "runs": len(results),
        "strict_passes": sum(bool(result["passed"]) for result in results),
        "strict_pass_rate": round(
            100 * sum(bool(result["passed"]) for result in results) / len(results), 2,
        ) if results else 0.0,
        "attempts": sum(len(result.get("attempts", [])) for result in results),
        "first_attempt_mean": round(statistics.mean(first_scores), 2) if first_scores else None,
        "selected_mean": round(statistics.mean(best_scores), 2) if best_scores else None,
        "mean_recovery_gain": round(statistics.mean(
            best - first for best, first in zip(best_scores, first_scores)
        ), 2) if best_scores and len(best_scores) == len(first_scores) else None,
        "runs_improved": sum(
            float(result["score"]) > float(result["attempts"][0]["score"])
            for result in results if result.get("attempts")
        ),
        "integrity_passes": sum(bool(result.get("integrity", {}).get("ok")) for result in results),
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


def generate_geometry_campaign_report(campaign_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    campaign_dir = Path(campaign_dir).resolve()
    output_dir = Path(output_dir).resolve()
    manifest = json.loads((campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8"))
    results = json.loads((campaign_dir / "results.json").read_text(encoding="utf-8"))
    summary = summarize_geometry_campaign(manifest, results)
    rows = geometry_report_rows(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8",
    )
    with (output_dir / "attempts.csv").open("w", newline="", encoding="utf-8") as stream:
        fieldnames = list(rows[0]) if rows else [
            "sample_id", "model", "attempt_id", "attempt_number", "score", "passed",
            "selected", "elapsed_seconds", "input_tokens", "output_tokens",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    render_geometry_trajectories(manifest, results, summary).save(
        output_dir / "repair-trajectories.png",
    )
    report = "\n".join([
        f"# Geometry Campaign: {summary['campaign_id']}",
        "",
        f"Protocol: `{summary['protocol']}`; manifest: `{summary['manifest_sha256']}`.",
        "",
        f"Runs: {summary['runs']}; strict passes: {summary['strict_passes']} "
        f"({summary['strict_pass_rate']:.2f}%); attempts: {summary['attempts']}.",
        f"First-attempt mean: {summary['first_attempt_mean']}; selected mean: "
        f"{summary['selected_mean']}; recovery gain: {summary['mean_recovery_gain']}.",
        "",
        "![Geometry repair trajectories](repair-trajectories.png)",
        "",
    ])
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary
