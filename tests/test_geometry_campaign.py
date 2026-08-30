from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.evaluation import geometry_campaign
from cad_evoloop.evaluation.geometry_split import build_geometry_split


def _sample() -> dict:
    return {
        "sample_id": "test:1",
        "dataset": "test",
        "task": "Reconstruct the part.",
        "input_images": ["test/1/input.png"],
        "ground_truth_step": "test/1/ground_truth.step",
        "category": "mechanical",
    }


def _manifest(tmp_path: Path) -> Path:
    image = tmp_path / "test/1/input.png"
    truth = tmp_path / "test/1/ground_truth.step"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    truth.write_bytes(b"step-secret")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": [_sample()],
    }), encoding="utf-8")
    return manifest


def test_stage_agent_inputs_excludes_ground_truth(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    job = tmp_path / "job"

    images = geometry_campaign.stage_agent_inputs(manifest, _sample(), job)

    assert len(images) == 1
    assert not list(job.rglob("*.step"))
    task = json.loads((job / "task.json").read_text(encoding="utf-8"))
    assert "ground_truth" not in json.dumps(task)
    assert task["output_requirement"].startswith("One native")


def test_geometry_verdict_is_actionable_without_file_paths() -> None:
    result = {
        "passed": False,
        "quality_tier": "failed",
        "score": 82.5,
        "coverage": 100.0,
        "checks": {
            "candidate_watertight": True,
            "voxel_iou": False,
            "normalized_chamfer": True,
            "bbox_relative_error": False,
            "volume_relative_error": True,
        },
        "acceptable_checks": {
            "candidate_watertight": True,
            "voxel_iou": False,
            "normalized_chamfer": True,
            "bbox_relative_error": False,
            "volume_relative_error": True,
        },
        "metrics": {
            "voxel_iou": 0.8,
            "normalized_chamfer": 0.009,
            "bbox_relative_error": 0.2,
            "volume_relative_error": 0.01,
        },
        "mismatch": {"candidate_to_ground_truth": {"p95_normalized": 0.03}},
        "candidate_geometry": {"watertight": True, "extents": [12, 20, 30]},
        "ground_truth_geometry": {"watertight": True, "extents": [10, 20, 30]},
        "alignment": {"scale_allowed": False},
        "candidate": "candidate.stl",
        "ground_truth": "secret/ground_truth.step",
    }

    verdict = geometry_campaign.geometry_verdict(result, "test:1")
    encoded = json.dumps(verdict)

    assert verdict["score"] == 82.5
    assert verdict["rubrics"][1]["status"] == "failed"
    assert "secret" not in encoded
    assert "ground_truth.step" not in encoded
    assert verdict["ground_truth_geometry"]["extents"] == [10, 20, 30]


def test_geometry_campaign_dry_run_binds_truth_hash(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _manifest(workspace / ".local/data")
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)

    result = geometry_campaign.run_geometry_campaign(
        manifest,
        campaign="dry-run",
        models=["test-model"],
        sample_ids={"test:1"},
        max_jobs=1,
        dry_run=True,
    )

    campaign_path = workspace / "evals/geometry-benchmarks/batch/dry-run/campaign-manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert result["status"] == "dry-run"
    assert campaign["jobs"][0]["ground_truth_sha256"]
    assert campaign["source_manifest_sha256"]
    assert campaign["protocol"] == "evocad-geometry-v2"


def test_geometry_campaign_binds_benchmark_split(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _manifest(workspace / ".local/data")
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    split = build_geometry_split(manifest, pilot_count=1)
    split_path = workspace / "split.json"
    split_path.write_text(json.dumps(split), encoding="utf-8")

    geometry_campaign.run_geometry_campaign(
        manifest,
        campaign="split-run",
        models=["test-model"],
        split_file=split_path,
        split_name="cost_pilot",
        dry_run=True,
    )

    campaign_path = workspace / "evals/geometry-benchmarks/batch/split-run/campaign-manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert campaign["benchmark_split"] == {
        "name": "cost_pilot",
        "split_sha256": split["split_sha256"],
        "source_sample_ids_sha256": split["source_sample_ids_sha256"],
    }


def test_codex_command_mounts_only_audited_autocad_server(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    image = tmp_path / "input.png"
    command = geometry_campaign.codex_command(
        "codex", "model", "medium", tmp_path, [image], "prompt",
        tmp_path / "audit.jsonl", tmp_path / "final.txt",
    )
    encoded = " ".join(command)

    assert "backends/autocad/audited.py" in encoded
    assert "AUTOCAD_MCP_AUDIT_PATH" in encoded
    assert "ground_truth" not in encoded
    assert str(image) in command


def test_repair_prompt_distinguishes_best_and_latest_verdict(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    template = tmp_path / "repair.md"
    template.write_text(
        "$previous_candidate\n$verdict\n$latest_verdict\n$skill_path\n",
        encoding="utf-8",
    )

    value = geometry_campaign._prompt(
        template,
        sample_id="sample",
        run_id="run",
        attempt_id="a003",
        candidate=tmp_path / "candidate.a003.dwg",
        previous_candidate=tmp_path / "candidate.a001.dwg",
        verdict=tmp_path / "a001.json",
        latest_verdict=tmp_path / "a002.json",
        reflection=tmp_path / "reflection.json",
    )

    assert "candidate.a001.dwg" in value
    assert "a001.json" in value
    assert "a002.json" in value


def test_repair_stopping_uses_stagnation_or_budget_not_a_fixed_two_attempts() -> None:
    common = {
        "passed": False,
        "timed_out": False,
        "return_code": 0,
        "has_candidate": True,
        "stagnation_limit": 2,
        "job_time_budget": 3600,
    }
    assert geometry_campaign.should_stop_repairs(
        **common, non_improving_attempts=1, elapsed_seconds=100,
    ) is False
    assert geometry_campaign.should_stop_repairs(
        **common, non_improving_attempts=2, elapsed_seconds=100,
    ) is True
    assert geometry_campaign.should_stop_repairs(
        **common, non_improving_attempts=0, elapsed_seconds=3600,
    ) is True


def test_attempt_timeout_is_bounded_by_remaining_job_budget() -> None:
    assert geometry_campaign.remaining_attempt_timeout(1800, 2400.0) == 1800
    assert geometry_campaign.remaining_attempt_timeout(1800, 37.9) == 37
    assert geometry_campaign.remaining_attempt_timeout(1800, -1.0) == 1
