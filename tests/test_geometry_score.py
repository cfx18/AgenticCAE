from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation import geometry_score


def test_protocol_v2_matches_implementation_thresholds() -> None:
    protocol_path = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "geometry-benchmarks"
        / "protocol-v2.json"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))

    assert protocol["protocol"] == geometry_score.PROTOCOL_ID
    assert protocol["strict_thresholds"] == geometry_score.DEFAULT_THRESHOLDS
    assert protocol["acceptable_thresholds"] == geometry_score.ACCEPTABLE_THRESHOLDS


def test_geometry_score_reports_missing_optional_dependencies(monkeypatch) -> None:
    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "OCP.BRep":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)

    with pytest.raises(RuntimeError, match="geometry.*extra"):
        geometry_score._dependencies()


def test_step_mesh_preserves_triangle_to_brep_face_provenance(tmp_path) -> None:
    pytest.importorskip("trimesh")
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    step = tmp_path / "box.step"
    writer = STEPControl_Writer()
    assert writer.Transfer(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(step)) == IFSelect_RetDone

    mesh = geometry_score._load_mesh(step)

    face_ids = mesh.face_attributes["brep_face_id"]
    descriptors = mesh.metadata["brep_face_descriptors"]
    assert len(face_ids) == len(mesh.faces)
    assert len(set(face_ids)) == 6
    assert len(descriptors) == 6
    assert {item["surface_type"] for item in descriptors.values()} == {"plane"}
    assert all(identifier.startswith("face-") for identifier in descriptors)


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
    assert identity["protocol"] == "evocad-geometry-v2"
    assert identity["parameters"]["thresholds"]["voxel_iou_min"] == 0.99
    assert identity["metrics"]["voxel_iou"] == 1.0
    assert identity["score"] == 100.0
    assert identity["coverage"] == 100.0
    assert identity["mismatch"]["candidate_to_ground_truth"]["max_normalized"] == 0.0
    assert identity["mismatch"]["localization"]["region_count"] == 0
    assert identity["mismatch"]["localization"]["uses_evaluator_ground_truth"] is True
    assert identity["mismatch"]["localization"]["distance_threshold_normalized"] == 0.006
    assert wrong["passed"] is False
    assert wrong["score"] < identity["score"]
    assert wrong["metrics"]["bbox_relative_error"] == pytest.approx(0.2)
    assert wrong["mismatch"]["localization"]["region_count"] > 0
    region = wrong["mismatch"]["localization"]["regions"][0]
    assert region["region_id"].startswith(("excess-", "missing-"))
    assert len(region["centroid"]) == 3
    assert region["p95_distance_normalized"] > 0


def test_localization_ignores_equivalent_surface_tessellation(tmp_path) -> None:
    trimesh = pytest.importorskip("trimesh")
    pytest.importorskip("OCP")
    coarse = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    vertices, faces = trimesh.remesh.subdivide(coarse.vertices, coarse.faces)
    refined = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    coarse_path = tmp_path / "coarse.stl"
    refined_path = tmp_path / "refined.stl"
    coarse.export(coarse_path)
    refined.export(refined_path)

    result = geometry_score.score_geometry_files(
        refined_path, coarse_path, sample_count=1000, voxel_resolution=24,
    )

    assert result["mismatch"]["localization"]["region_count"] == 0
    assert result["mismatch"]["candidate_to_ground_truth"]["p95_normalized"] == 0.0
    assert result["mismatch"]["ground_truth_to_candidate"]["p95_normalized"] == 0.0


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
    assert result["summary"]["localization_false_region_pairs"] == 0
    assert result["results"][0]["sample_id"] == "paired"
    assert output.is_file()
