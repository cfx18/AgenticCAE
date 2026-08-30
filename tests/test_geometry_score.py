from __future__ import annotations

import pytest
import json

from cad_evoloop.evaluation import geometry_score


def test_geometry_score_reports_missing_optional_dependencies(monkeypatch) -> None:
    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "OCP.BRep":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)

    with pytest.raises(RuntimeError, match="geometry.*extra"):
        geometry_score._dependencies()


def test_geometry_score_accepts_identity_and_rejects_scaled_shape(tmp_path) -> None:
    trimesh = pytest.importorskip("trimesh")
    pytest.importorskip("OCP")
    source = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    truth = tmp_path / "truth.stl"
    scaled = tmp_path / "scaled.stl"
    source.export(truth)
    changed = source.copy()
    changed.apply_scale(1.2)
    changed.export(scaled)

    identity = geometry_score.score_geometry_files(
        truth, truth, sample_count=1000, voxel_resolution=24,
    )
    wrong = geometry_score.score_geometry_files(
        scaled, truth, sample_count=1000, voxel_resolution=24,
    )

    assert identity["passed"] is True
    assert identity["protocol"] == "evocad-geometry-v1"
    assert identity["parameters"]["thresholds"]["voxel_iou_min"] == 0.95
    assert identity["metrics"]["voxel_iou"] == 1.0
    assert wrong["passed"] is False
    assert wrong["metrics"]["bbox_relative_error"] == pytest.approx(0.2)


def test_calibrates_only_samples_with_step_and_stl(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "calibration.json"
    manifest.write_text(json.dumps({"samples": [
        {"sample_id": "paired", "dataset": "test", "ground_truth_stl": "a.stl", "ground_truth_step": "a.step"},
        {"sample_id": "code-only", "dataset": "test", "ground_truth_code": "a.py"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(geometry_score, "score_geometry_files", lambda *args, **kwargs: {
        "passed": True,
        "checks": {"voxel_iou": True},
        "metrics": {"voxel_iou": 1.0, "normalized_chamfer": 0.0, "volume_relative_error": 0.0},
    })

    result = geometry_score.calibrate_geometry_manifest(manifest, output)

    assert result["summary"]["pairs"] == 1
    assert result["summary"]["passed"] == 1
    assert result["results"][0]["sample_id"] == "paired"
    assert output.is_file()
