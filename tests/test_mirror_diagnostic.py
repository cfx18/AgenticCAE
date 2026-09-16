from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
trimesh = pytest.importorskip("trimesh")


@pytest.fixture
def diagnostic():
    path = Path(__file__).resolve().parents[1] / "evals/geometry-benchmarks/scripts/mirror_diagnostic.py"
    spec = importlib.util.spec_from_file_location("mirror_diagnostic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_reflection_preserves_bounds_volume_and_winding(diagnostic, axis):
    mesh = trimesh.creation.box(extents=[2, 3, 4])
    mesh.apply_translation([9, -3, 7])
    transform = diagnostic.reflection_matrix(mesh.bounds, axis)
    assert np.linalg.det(transform[:3, :3]) == pytest.approx(-1)
    mirrored = mesh.copy().apply_transform(transform)
    assert mirrored.volume == pytest.approx(mesh.volume)
    assert mirrored.is_watertight and mirrored.is_winding_consistent
    np.testing.assert_allclose(mirrored.bounds, mesh.bounds)
    np.testing.assert_allclose(transform @ transform, np.eye(4))


def test_refuses_existing_output_before_scoring(diagnostic, tmp_path, monkeypatch):
    mesh = trimesh.creation.box()
    candidate, truth = tmp_path / "candidate.stl", tmp_path / "gt.stl"
    mesh.export(candidate)
    mesh.export(truth)
    output = tmp_path / "result"
    output.mkdir()
    monkeypatch.setattr(diagnostic, "project_root", lambda: tmp_path)
    with pytest.raises(FileExistsError):
        diagnostic.run(candidate, truth, output)


def test_reports_posthoc_provenance_and_leaves_sources_unchanged(diagnostic, tmp_path, monkeypatch):
    candidate, truth = tmp_path / "candidate.stl", tmp_path / "gt.stl"
    trimesh.creation.box().export(candidate)
    trimesh.creation.box().export(truth)
    original = candidate.read_bytes()
    monkeypatch.setattr(diagnostic, "project_root", lambda: tmp_path)
    calls = []

    def score(path, gt, **kwargs):
        calls.append((path, kwargs))
        assert trimesh.load_mesh(path).volume > 0
        return {"score": 100, "passed": True, "metrics": {}, "alignment": {}}

    monkeypatch.setattr(diagnostic, "score_geometry_files", score)
    result = diagnostic.run(candidate, truth, tmp_path / "result")
    assert result["eligible_for_original_agent_score"] is False
    assert result["source_integrity_verified"] is True
    assert len(calls) == 4
    assert candidate.read_bytes() == original
    assert all(kwargs == {"sample_count": 20000, "voxel_resolution": 64} for _, kwargs in calls)
