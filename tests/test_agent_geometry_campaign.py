from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation import agent_geometry_campaign


def canonical(value: dict, excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_frozen_agent_campaign_dry_run_binds_samples_model_and_sources(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    benchmark = workspace / "evals/geometry-benchmarks"
    data = workspace / ".local/data"
    sample = data / "sample"
    sample.mkdir(parents=True)
    (sample / "input.png").write_bytes(b"input")
    (sample / "truth.step").write_bytes(b"truth")
    manifest = data / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": [{
            "sample_id": "sample:1", "dataset": "test", "task": "image-to-cad",
            "input_images": ["sample/input.png"], "ground_truth_step": "sample/truth.step",
        }],
    }), encoding="utf-8")
    splits = benchmark / "splits"
    splits.mkdir(parents=True)
    source_split = splits / "source.json"
    source_split.write_text("{}", encoding="utf-8")
    selection = {
        "schema_version": "1.0",
        "protocol": "test",
        "kind": "frozen-agent-evaluation-selection",
        "source_split": "source.json",
        "source_split_sha256": hashlib.sha256(b"{}").hexdigest(),
        "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "sample_count": 1,
        "sample_ids": ["sample:1"],
    }
    selection["selection_sha256"] = canonical(selection, "selection_sha256")
    selection_path = splits / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    source_files = [
        workspace / "src/cad_evoloop/evaluation/geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/geometry_features.py",
        workspace / "src/cad_evoloop/evaluation/agent_geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/detached_campaign.py",
        workspace / "src/cad_evoloop/backends/autocad/topology.py",
        workspace / "mcp/autocad-topology/EvoCadTopology.cs",
        workspace / ".agents/skills/autocad-image-modeling/SKILL.md",
        workspace / "evals/geometry-benchmarks/protocol-v2.json",
        workspace / "evals/geometry-benchmarks/agent-loop-v3.json",
    ]
    for path in source_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source", encoding="utf-8")
    monkeypatch.setattr(agent_geometry_campaign, "project_root", lambda: workspace)

    result = agent_geometry_campaign.run_agent_geometry_campaign(
        manifest, selection_path, campaign="agent-dry", dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["jobs"] == [
        {"sample_id": "sample:1", "project_id": "sample-1", "model": "gpt-5.6-sol"}
    ]
    campaign_manifest = result["campaign_manifest"]
    assert campaign_manifest["selection"]["sample_ids"] == ["sample:1"]
    assert campaign_manifest["model"]["name"] == "gpt-5.6-sol"
    assert campaign_manifest["agent_condition"] == "durable-kernel-boolean-lineage-v4"
    assert campaign_manifest["execution"]["boolean_face_lineage"] == {
        "protocol": "evocad-boolean-face-lineage-v2",
        "capture": "native_topology_before_and_after_each_core_job",
        "operation_metadata_is_non_restrictive": True,
    }
    assert campaign_manifest["execution"]["attempt_recovery"] == {
        "protocol": "geometry-attempt-checkpoint-v1",
        "stages": ["action_running", "action_completed", "verifier_completed"],
        "preserve_interrupted_traces": True,
    }
    assert "python" in campaign_manifest["runtime_environment"]
    assert set(campaign_manifest["runtime_environment"]["packages"]) == {
        "cadquery-ocp", "numpy", "scipy", "trimesh",
    }
    assert {
        "src/cad_evoloop/evaluation/geometry_features.py",
        "src/cad_evoloop/evaluation/detached_campaign.py",
        "src/cad_evoloop/backends/autocad/topology.py",
        "mcp/autocad-topology/EvoCadTopology.cs",
    } <= set(campaign_manifest["agent_source_hashes"])


def test_preflight_reports_missing_geometry_distribution() -> None:
    environment = {
        "packages": {
            "cadquery-ocp": None,
            "numpy": "1.26.4",
            "scipy": "1.15.3",
            "trimesh": "4.12.2",
        },
        "codex": {"version": "codex-cli test"},
    }

    with pytest.raises(RuntimeError, match="cadquery-ocp"):
        agent_geometry_campaign.require_geometry_environment(environment)


def test_geometry_work_unit_reserves_one_host_interruption_recovery(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    sample_dir = data / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "input.png").write_bytes(b"input")
    manifest = data / "manifest.json"
    manifest.write_text('{"samples":[]}', encoding="utf-8")

    store = agent_geometry_campaign._create_sample_project(
        projects_root=tmp_path / "projects",
        campaign="recovery-test",
        sample={"sample_id": "sample:1", "input_images": ["sample/input.png"]},
        manifest_path=manifest,
        model="gpt-5.6-sol",
    )

    unit = store.load()["work_units"]["geometry-reconstruction"]
    assert unit["max_attempts"] == 2


def test_feedback_only_campaign_schedules_actionable_reviewed_samples(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    benchmark = workspace / "evals/geometry-benchmarks"
    data = workspace / ".local/data"
    sample = data / "sample"
    sample.mkdir(parents=True)
    for name in ("one.png", "one.step", "two.png", "two.step"):
        (sample / name).write_bytes(name.encode())
    manifest = data / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": [
            {
                "sample_id": "sample:1", "dataset": "test", "task": "image-to-cad",
                "input_images": ["sample/one.png"],
                "ground_truth_step": "sample/one.step",
            },
            {
                "sample_id": "sample:2", "dataset": "test", "task": "image-to-cad",
                "input_images": ["sample/two.png"],
                "ground_truth_step": "sample/two.step",
            },
        ],
    }), encoding="utf-8")
    splits = benchmark / "splits"
    splits.mkdir(parents=True)
    source_split = splits / "source.json"
    source_split.write_text("{}", encoding="utf-8")
    selection = {
        "schema_version": "1.0",
        "protocol": "test",
        "kind": "frozen-agent-evaluation-selection",
        "source_split": "source.json",
        "source_split_sha256": hashlib.sha256(b"{}").hexdigest(),
        "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "sample_count": 2,
        "sample_ids": ["sample:1", "sample:2"],
    }
    selection["selection_sha256"] = canonical(selection, "selection_sha256")
    selection_path = splits / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    source_files = [
        workspace / "src/cad_evoloop/evaluation/geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/agent_geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/review_feedback.py",
        workspace / "src/cad_evoloop/evaluation/detached_campaign.py",
        workspace / ".agents/skills/autocad-image-modeling/SKILL.md",
        workspace / "evals/geometry-benchmarks/protocol-v2.json",
        workspace / "evals/geometry-benchmarks/agent-loop-v3.json",
        workspace / "evals/geometry-benchmarks/human-feedback-v1.json",
    ]
    for path in source_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source", encoding="utf-8")
    feedback = {
        "schema_version": "1.0",
        "protocol": "evocad-human-feedback-v1",
        "source": {
            "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "review_bundle_sha256": "bundle-digest",
            "review_ledger_sha256": "ledger-digest",
            "review_ledger_head_sha256": "ledger-head",
        },
        "active_review_count": 1,
        "sample_count": 1,
        "sample_ids": ["sample:1"],
        "samples": {
            "sample:1": {
                "sample_id": "sample:1",
                "route": "agent_repair",
                "requires_human_clarification": False,
                "issue_types": ["agent_geometry"],
                "clarification_questions": [],
                "reviews": [],
            },
        },
        "system_improvement_candidates": [],
    }
    feedback["feedback_manifest_sha256"] = canonical(
        feedback, "feedback_manifest_sha256",
    )
    feedback_path = benchmark / "feedback.json"
    feedback_path.write_text(json.dumps(feedback), encoding="utf-8")
    monkeypatch.setattr(agent_geometry_campaign, "project_root", lambda: workspace)

    result = agent_geometry_campaign.run_agent_geometry_campaign(
        manifest,
        selection_path,
        campaign="feedback-dry",
        human_feedback=feedback_path,
        feedback_only=True,
        dry_run=True,
    )

    assert result["jobs"] == [{
        "sample_id": "sample:1",
        "project_id": "sample-1",
        "model": "gpt-5.6-sol",
        "feedback_route": "agent_repair",
    }]
    campaign_manifest = result["campaign_manifest"]
    assert campaign_manifest["agent_condition"] == "durable-kernel-human-feedback-checkpoint-v2"
    assert campaign_manifest["selection"]["source_sample_count"] == 2
    assert campaign_manifest["selection"]["sample_count"] == 1
    assert campaign_manifest["human_feedback"]["feedback_only"] is True
    assert campaign_manifest["human_feedback"]["review_bundle_sha256"] == "bundle-digest"


def test_frozen_selection_detects_identifier_edits(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    value = {
        "kind": "frozen-agent-evaluation-selection",
        "source_split": "source.json",
        "source_split_sha256": hashlib.sha256(b"{}").hexdigest(),
        "sample_count": 1,
        "sample_ids": ["sample:1"],
    }
    value["selection_sha256"] = canonical(value, "selection_sha256")
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    value["sample_ids"] = ["sample:2"]
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        agent_geometry_campaign.load_frozen_selection(path)
