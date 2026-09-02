from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation import geometry_feature_backfill as backfill
from cad_evoloop.evaluation import geometry_feature_report as feature_report


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _score() -> dict:
    return {
        "passed": False, "quality_tier": "failed", "score": 50.0, "coverage": 100.0,
        "checks": {
            "candidate_watertight": True, "voxel_iou": False,
            "normalized_chamfer": False, "bbox_relative_error": True,
            "volume_relative_error": True,
        },
        "acceptable_checks": {
            "candidate_watertight": True, "voxel_iou": False,
            "normalized_chamfer": False, "bbox_relative_error": True,
            "volume_relative_error": True,
        },
        "metrics": {
            "voxel_iou": 0.5, "chamfer_distance": 1.0, "normalized_chamfer": 0.1,
            "bbox_relative_error": 0.0, "volume_relative_error": 0.0,
            "surface_area_relative_error": 0.0,
        },
        "alignment": {
            "type": "right-handed-axis-permutation-plus-translation",
            "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "candidate_center": [0, 0, 0], "ground_truth_center": [0, 0, 0],
            "scale_allowed": False,
        },
        "mismatch": {"localization": {"regions": [{
            "region_id": "excess-01", "direction": "candidate_to_ground_truth",
            "centroid": [0, 0, 0], "bbox": {"min": [0, 0, 0], "max": [1, 1, 0]},
        }]}},
        "candidate_geometry": {
            "vertices": 8, "triangles": 12, "watertight": True, "volume": 1,
            "surface_area": 6, "extents": [1, 1, 1],
        },
        "ground_truth_geometry": {
            "vertices": 8, "triangles": 12, "watertight": True, "volume": 1,
            "surface_area": 6, "extents": [1, 1, 1],
        },
    }


def test_backfill_is_resumable_and_does_not_modify_frozen_campaign(tmp_path, monkeypatch) -> None:
    workspace = tmp_path
    campaign = workspace / "evals/geometry-benchmarks/batch/baseline"
    job = campaign / "sample-1/model"
    attempt = job / "attempts/a001"
    source = workspace / ".local/data/manifest.json"
    truth = source.parent / "truth.step"
    for path in (job / "candidate.dwg", job / "candidate.stl", truth):
        _write(path, "artifact")
    _write(attempt / "mcp-audit.jsonl", "")
    source_value = {"samples": [{"sample_id": "sample:1", "ground_truth_step": "truth.step"}]}
    source.write_text(json.dumps(source_value), encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "campaign_id": "baseline", "source_manifest_sha256": source_hash,
    }
    _write(campaign / "campaign-manifest.json", json.dumps(manifest))
    results = [{
        "sample_id": "sample:1", "model": "model", "selected_attempt_id": "a001",
        "job_dir": str(job),
    }]
    results_path = _write(campaign / "results.json", json.dumps(results))
    frozen_hash = hashlib.sha256(results_path.read_bytes()).hexdigest()
    _write(workspace / "mcp/autocad-topology/EvoCadTopology.cs", "source")
    executable = _write(workspace / "accoreconsole.exe", "exe")
    plugin = _write(workspace / "EvoCadTopology.dll", "plugin")

    monkeypatch.setattr(backfill, "project_root", lambda: workspace)
    monkeypatch.setenv("AUTOCAD_CORE_CONSOLE", str(executable))
    monkeypatch.setenv("AUTOCAD_TOPOLOGY_PLUGIN", str(plugin))
    monkeypatch.setattr(backfill, "score_geometry_files", lambda *args, **kwargs: _score())

    calls = []
    def export(*args, **kwargs):
        calls.append(args)
        Path(args[2]).write_text(json.dumps({
            "schema_version": "1.0", "entities": [{
                "handle": "1", "faces": [{
                    "id": "f1", "bounds": {"min": [0, 0, 0], "max": [1, 1, 0]},
                    "surface": {"type": "plane"}, "edge_ids": [],
                }], "edges": [],
            }], "errors": [],
        }), encoding="utf-8")
        Path(kwargs["query_output_path"]).write_text(json.dumps({"queries": [{
            "query_id": "excess-01#00", "entity_handle": "1", "face_id": "f1",
            "distance": 0.0, "method": "trimmed_surface",
        }]}), encoding="utf-8")

    monkeypatch.setattr(backfill, "export_topology_core", export)
    output = workspace / "reports/backfill"
    first = backfill.backfill_geometry_features(campaign, source, output)
    second = backfill.backfill_geometry_features(campaign, source, output)

    assert first["metrics"]["exact_face_mapping_coverage_percent"] == 100.0
    assert second["metrics"] == first["metrics"]
    assert len(calls) == 1
    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == frozen_hash
    assert json.loads((output / "backfill-manifest.json").read_text())["sample_ids"] == ["sample:1"]

    monkeypatch.setattr(feature_report, "project_root", lambda: workspace)
    report = feature_report.generate_feature_backfill_report(
        output, workspace / "reports/backfill-analysis",
    )
    assert report["accuracy_status"] == "unmeasured_without_expert_face_labels"
    assert report["directions"]["candidate_to_ground_truth"]["zero_distance_count"] == 1

    (job / "candidate.dwg").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Cached backfill artifact changed"):
        backfill.backfill_geometry_features(campaign, source, output)
