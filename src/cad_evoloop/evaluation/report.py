"""Generate auditable campaign summaries and paper-ready vector figures."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import statistics
from typing import Any

from .campaign import validate_campaign_manifest


MODEL_COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")


def _usage(result: dict[str, Any], key: str) -> int:
    return int(result.get("total_usage", result.get("usage", {})).get(key, 0) or 0)


def _vlm_usage(result: dict[str, Any], key: str) -> int:
    return int(result.get("vlm_usage", {}).get(key, 0) or 0)


def campaign_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        attempts = result.get("attempts", [])
        first_eqc = float(attempts[0].get("eqc", 0.0)) if attempts else 0.0
        final_eqc = float(result.get("eqc", 0.0) or 0.0)
        last_attempt = attempts[-1].get("attempt_id") if attempts else None
        rows.append({
            "sample_id": result["sample_id"],
            "model": result["model"],
            "status": result.get("status", "unknown"),
            "eqc": final_eqc,
            "legacy_score": float(result.get("score", 0.0) or 0.0),
            "deterministic_coverage": float(result.get("coverage", 0.0) or 0.0),
            "attempts": len(attempts),
            "first_eqc": first_eqc,
            "eqc_gain": round(final_eqc - first_eqc, 2),
            "selected_attempt_id": result.get("selected_attempt_id"),
            "selected_not_last": bool(attempts and result.get("selected_attempt_id") != last_attempt),
            "elapsed_seconds": float(result.get("elapsed_seconds", 0.0) or 0.0),
            "agent_input_tokens": _usage(result, "input_tokens"),
            "agent_cached_input_tokens": _usage(result, "cached_input_tokens"),
            "agent_output_tokens": _usage(result, "output_tokens"),
            "vlm_input_tokens": _vlm_usage(result, "input_tokens"),
            "vlm_output_tokens": _vlm_usage(result, "output_tokens"),
            "integrity_ok": result.get("integrity", {}).get("ok") is True,
        })
    return rows


def summarize_campaign(
    manifest: dict[str, Any], results: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_campaign_manifest(manifest)
    expected = {
        (item["sample_id"], item["model"])
        for item in manifest.get("execution", {}).get("jobs", [])
    }
    actual = {(item.get("sample_id"), item.get("model")) for item in results}
    if expected != actual or len(actual) != len(results):
        raise ValueError("Campaign results do not match the immutable job matrix")
    rows = campaign_rows(results)
    if not all(row["integrity_ok"] for row in rows):
        raise ValueError("Campaign contains a result with failed or missing ledger integrity")
    models = [item["name"] for item in manifest.get("models", [])]
    per_model = []
    for model in models:
        selected = [row for row in rows if row["model"] == model]
        eqcs = [row["eqc"] for row in selected]
        per_model.append({
            "model": model,
            "runs": len(selected),
            "passed": sum(row["status"] == "passed" for row in selected),
            "pass_rate": round(100.0 * sum(row["status"] == "passed" for row in selected) / len(selected), 2),
            "mean_eqc": round(statistics.mean(eqcs), 2),
            "median_eqc": round(statistics.median(eqcs), 2),
            "mean_attempts": round(statistics.mean(row["attempts"] for row in selected), 2),
            "elapsed_seconds": round(sum(row["elapsed_seconds"] for row in selected), 3),
            "agent_input_tokens": sum(row["agent_input_tokens"] for row in selected),
            "agent_output_tokens": sum(row["agent_output_tokens"] for row in selected),
            "vlm_input_tokens": sum(row["vlm_input_tokens"] for row in selected),
            "vlm_output_tokens": sum(row["vlm_output_tokens"] for row in selected),
        })
    eqcs = [row["eqc"] for row in rows]
    first = [row["first_eqc"] for row in rows]
    return {
        "schema_version": "1.0",
        "campaign_id": manifest["campaign_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "runs": len(rows),
        "passed": sum(row["status"] == "passed" for row in rows),
        "pass_rate": round(100.0 * sum(row["status"] == "passed" for row in rows) / len(rows), 2),
        "mean_eqc": round(statistics.mean(eqcs), 2),
        "median_eqc": round(statistics.median(eqcs), 2),
        "first_attempt_mean_eqc": round(statistics.mean(first), 2),
        "mean_recovery_gain": round(statistics.mean(eqcs) - statistics.mean(first), 2),
        "runs_improved": sum(row["eqc_gain"] > 0 for row in rows),
        "selected_not_last": sum(row["selected_not_last"] for row in rows),
        "attempts": sum(row["attempts"] for row in rows),
        "stable_elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows), 3),
        "per_model": per_model,
    }


def _svg_text(x: float, y: float, value: str, **attributes: Any) -> str:
    attrs = " ".join(f'{key.replace("_", "-")}="{html.escape(str(item))}"' for key, item in attributes.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" {attrs}>{html.escape(value)}</text>'


def render_eqc_by_sample(rows: list[dict[str, Any]], models: list[str]) -> str:
    samples = list(dict.fromkeys(row["sample_id"] for row in rows))
    width, height = 1280, 620
    left, right, top, bottom = 76, 28, 52, 105
    plot_w, plot_h = width - left - right, height - top - bottom
    group_w = plot_w / len(samples)
    bar_w = min(28.0, group_w / (len(models) + 1))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        _svg_text(left, 28, "Evidence-Qualified Completion by Sample", font_family="Arial", font_size="20", font_weight="700", fill="#171717"),
    ]
    for tick in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - tick / 100)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#D7D7D7" stroke-width="1"/>')
        parts.append(_svg_text(left - 12, y + 5, str(tick), text_anchor="end", font_family="Arial", font_size="12", fill="#555555"))
    indexed = {(row["sample_id"], row["model"]): row for row in rows}
    for sample_index, sample in enumerate(samples):
        center = left + group_w * (sample_index + 0.5)
        start = center - bar_w * len(models) / 2
        for model_index, model in enumerate(models):
            row = indexed[(sample, model)]
            value = row["eqc"]
            x = start + model_index * bar_w
            y = top + plot_h * (1 - value / 100)
            h = top + plot_h - y
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w-3:.1f}" height="{h:.1f}" fill="{MODEL_COLORS[model_index % len(MODEL_COLORS)]}"/>')
        parts.append(_svg_text(center, height - bottom + 28, sample[:8], text_anchor="middle", font_family="Consolas", font_size="12", fill="#333333"))
    legend_x = width - right - 430
    for index, model in enumerate(models):
        x = legend_x + index * 145
        parts.append(f'<rect x="{x}" y="18" width="12" height="12" fill="{MODEL_COLORS[index % len(MODEL_COLORS)]}"/>')
        parts.append(_svg_text(x + 18, 29, model.replace("gpt-5.6-", ""), font_family="Arial", font_size="12", fill="#333333"))
    parts.append(_svg_text(20, top + plot_h / 2, "EQC (%)", transform=f"rotate(-90 20 {top + plot_h / 2:.1f})", text_anchor="middle", font_family="Arial", font_size="13", fill="#333333"))
    parts.append("</svg>\n")
    return "".join(parts)


def render_recovery_scatter(rows: list[dict[str, Any]], models: list[str]) -> str:
    width, height = 720, 660
    left, right, top, bottom = 82, 35, 52, 72
    plot_w, plot_h = width - left - right, height - top - bottom
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        _svg_text(left, 28, "Verifier-Guided Recovery", font_family="Arial", font_size="20", font_weight="700", fill="#171717"),
    ]
    legend_x = width - right - 275
    for index, model in enumerate(models):
        x = legend_x + index * 92
        parts.append(f'<rect x="{x}" y="18" width="11" height="11" fill="{MODEL_COLORS[index % len(MODEL_COLORS)]}"/>')
        parts.append(_svg_text(x + 16, 28, model.replace("gpt-5.6-", ""), font_family="Arial", font_size="11", fill="#333333"))
    for tick in (0, 25, 50, 75, 100):
        x = left + plot_w * tick / 100
        y = top + plot_h * (1 - tick / 100)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_h}" stroke="#E2E2E2"/>')
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#E2E2E2"/>')
        parts.append(_svg_text(x, top + plot_h + 24, str(tick), text_anchor="middle", font_family="Arial", font_size="12", fill="#555555"))
        parts.append(_svg_text(left - 12, y + 5, str(tick), text_anchor="end", font_family="Arial", font_size="12", fill="#555555"))
    parts.append(f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top}" stroke="#777777" stroke-dasharray="6 5"/>')
    model_index = {model: index for index, model in enumerate(models)}
    for row in rows:
        x = left + plot_w * row["first_eqc"] / 100
        y = top + plot_h * (1 - row["eqc"] / 100)
        color = MODEL_COLORS[model_index[row["model"]] % len(MODEL_COLORS)]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" fill-opacity="0.78" stroke="#FFFFFF" stroke-width="1.5"><title>{html.escape(row["sample_id"][:8])}: {row["first_eqc"]:.2f} to {row["eqc"]:.2f}</title></circle>')
    parts.append(_svg_text(left + plot_w / 2, height - 18, "First-attempt EQC (%)", text_anchor="middle", font_family="Arial", font_size="13", fill="#333333"))
    parts.append(_svg_text(20, top + plot_h / 2, "Selected EQC (%)", transform=f"rotate(-90 20 {top + plot_h / 2:.1f})", text_anchor="middle", font_family="Arial", font_size="13", fill="#333333"))
    parts.append("</svg>\n")
    return "".join(parts)


def generate_campaign_report(campaign_dir: Path, output_dir: Path) -> dict[str, Any]:
    campaign_dir = Path(campaign_dir).resolve()
    manifest = json.loads((campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8"))
    results = json.loads((campaign_dir / "results.json").read_text(encoding="utf-8"))
    summary = summarize_campaign(manifest, results)
    rows = campaign_rows(results)
    models = [item["name"] for item in manifest["models"]]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "eqc-by-sample.svg").write_text(render_eqc_by_sample(rows, models), encoding="utf-8")
    (output_dir / "recovery-scatter.svg").write_text(render_recovery_scatter(rows, models), encoding="utf-8")
    model_lines = [
        f"| {item['model']} | {item['runs']} | {item['passed']} | {item['mean_eqc']:.2f} | {item['median_eqc']:.2f} | {item['mean_attempts']:.2f} |"
        for item in summary["per_model"]
    ]
    report = "\n".join([
        f"# Campaign Report: {summary['campaign_id']}",
        "",
        f"Manifest SHA-256: `{summary['manifest_sha256']}`",
        "",
        f"Runs: {summary['runs']}; strict passes: {summary['passed']} ({summary['pass_rate']:.2f}%); mean EQC: {summary['mean_eqc']:.2f}.",
        f"First-attempt mean EQC: {summary['first_attempt_mean_eqc']:.2f}; mean recovery gain: {summary['mean_recovery_gain']:.2f} points.",
        f"Runs improved: {summary['runs_improved']}; best-checkpoint rollbacks: {summary['selected_not_last']}; attempts: {summary['attempts']}.",
        "",
        "| Model | Runs | Passed | Mean EQC | Median EQC | Mean attempts |",
        "|---|---:|---:|---:|---:|---:|",
        *model_lines,
        "",
        "## Figures",
        "",
        "![EQC by sample](eqc-by-sample.svg)",
        "",
        "![Verifier-guided recovery](recovery-scatter.svg)",
        "",
    ])
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary
