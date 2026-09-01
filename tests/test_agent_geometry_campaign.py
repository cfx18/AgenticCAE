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
        workspace / "src/cad_evoloop/evaluation/agent_geometry_campaign.py",
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
    assert campaign_manifest["agent_condition"] == "durable-kernel-compat-v1"
    assert "python" in campaign_manifest["runtime_environment"]
    assert set(campaign_manifest["runtime_environment"]["packages"]) == {
        "cadquery-ocp", "numpy", "scipy", "trimesh",
    }


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
