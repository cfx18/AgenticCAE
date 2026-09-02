"""Summarize native face attribution evidence without claiming unlabeled accuracy."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics
from typing import Any

from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _inside(path: str | Path, root: Path, name: str) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} must be inside workspace: {root}") from exc
    return resolved


def _direction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distances = [row["minimum_face_distance_normalized"] for row in rows]
    return {
        "region_count": len(rows),
        "exact_face_assigned_count": sum(row["exact_face_assigned"] for row in rows),
        "high_confidence_count": sum(row["confidence"] == "high" for row in rows),
        "zero_distance_count": sum(value <= 1e-8 for value in distances),
        "within_localization_threshold_count": sum(value <= 0.006 for value in distances),
        "median_minimum_face_distance_normalized": round(statistics.median(distances), 6),
        "feature_candidate_region_count": sum(row["feature_candidate_count"] > 0 for row in rows),
        "operation_attributed_region_count": sum(row["operation_candidate_count"] > 0 for row in rows),
    }


def generate_feature_backfill_report(
    backfill_dir: str | Path, output_dir: str | Path,
) -> dict[str, Any]:
    workspace = project_root().resolve()
    backfill_dir = _inside(backfill_dir, workspace, "backfill_dir")
    output_dir = _inside(output_dir, workspace, "output_dir")
    manifest_path = backfill_dir / "backfill-manifest.json"
    summary_path = backfill_dir / "summary.json"
    if not manifest_path.is_file() or not summary_path.is_file():
        raise ValueError(f"Incomplete feature backfill: {backfill_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    completed_records = 0
    for record_path in sorted(backfill_dir.glob("**/record.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") != "completed":
            continue
        completed_records += 1
        verdict_artifact = record["artifacts"]["verdict"]
        verdict_path = _inside(verdict_artifact["path"], backfill_dir, "verdict")
        if sha256_file(verdict_path) != verdict_artifact["sha256"]:
            raise ValueError(f"Backfill verdict hash mismatch: {verdict_path}")
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        localization = ((verdict.get("mismatch") or {}).get("localization") or {})
        for region in localization.get("regions", []):
            faces = region.get("candidate_topology_faces") or []
            distances = [
                float(face["minimum_trimmed_face_distance_normalized"])
                for face in faces
                if face.get("minimum_trimmed_face_distance_normalized") is not None
            ]
            rows.append({
                "sample_id": record["sample_id"], "model": record["model"],
                "selected_attempt_id": record["selected_attempt_id"],
                "region_id": region["region_id"], "direction": region["direction"],
                "error_type": region.get("error_type"),
                "confidence": region.get("topology_mapping_confidence", "unknown"),
                "exact_face_assigned": bool((region.get("exact_face_query") or {}).get("mapped")),
                "minimum_face_distance_normalized": min(distances) if distances else float("inf"),
                "candidate_face_count": len(faces),
                "feature_candidate_count": len(region.get("engineering_feature_candidates") or []),
                "operation_candidate_count": len(region.get("responsible_operation_candidates") or []),
            })
    finite_rows = [row for row in rows if row["minimum_face_distance_normalized"] != float("inf")]
    directions = {
        direction: _direction_summary([row for row in finite_rows if row["direction"] == direction])
        for direction in sorted({row["direction"] for row in finite_rows})
    }
    report = {
        "schema_version": "1.0", "protocol": "evocad-native-feature-analysis-v1",
        "bindings": {
            "backfill_protocol": manifest.get("protocol"),
            "backfill_manifest_sha256": manifest.get("manifest_sha256"),
            "backfill_manifest_file_sha256": sha256_file(manifest_path),
            "backfill_summary_file_sha256": sha256_file(summary_path),
        },
        "sample_count": completed_records, "region_count": len(rows),
        "directions": directions,
        "accuracy_status": "unmeasured_without_expert_face_labels",
        "interpretation": {
            "candidate_to_ground_truth": "Queries originate on candidate surfaces and identify excess or displaced candidate faces.",
            "ground_truth_to_candidate": "Queries originate on missing truth surfaces; returned candidate faces are nearest surviving boundaries, not the absent feature itself.",
            "coverage": "Assignment coverage measures whether the system returned a face, not whether an expert judges the attribution correct.",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "analysis.json", report)
    with (output_dir / "regions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["sample_id"])
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Native Feature Localization Backfill", "",
        f"Samples: {completed_records}; localized regions: {len(rows)}.", "",
        "Assignment coverage is not localization accuracy. Accuracy remains unmeasured until expert face labels are available.", "",
        "## Directional diagnostics", "",
    ]
    for direction, values in directions.items():
        lines.extend([
            f"- `{direction}`: {values['region_count']} regions; "
            f"{values['high_confidence_count']} high confidence; "
            f"{values['within_localization_threshold_count']} within d<=0.006; "
            f"{values['feature_candidate_region_count']} with analytic feature candidates; "
            f"{values['operation_attributed_region_count']} with operation attribution.",
        ])
    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
