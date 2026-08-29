from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation.campaign import (
    build_campaign_manifest,
    validate_campaign_manifest,
    write_immutable_manifest,
)


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    eval_root = workspace / "evals/cad-1000-hours"
    sample = eval_root / "samples/dev-1"
    sample.mkdir(parents=True)
    (sample / "task_desc.json").write_text('{"task":"draw"}', encoding="utf-8")
    (sample / "rubrics.json").write_text('{"rubrics":[]}', encoding="utf-8")
    (sample / "input_files").mkdir()
    (sample / "input_files/reference.png").write_bytes(b"png")
    (eval_root / "manifest.json").write_text(json.dumps({
        "source": "dataset", "revision": "r1", "license": None,
    }), encoding="utf-8")
    (eval_root / "improvement").mkdir()
    (eval_root / "improvement/split.json").write_text(json.dumps({
        "development": ["dev-1"], "holdout": ["test-1"],
    }), encoding="utf-8")
    source = workspace / "src/component.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    return eval_root, source


def build(eval_root: Path, source: Path, **overrides) -> dict:
    values = {
        "campaign_id": "campaign-1",
        "mode": "development",
        "eval_root": eval_root,
        "sample_ids": ["dev-1"],
        "models": [{"name": "model", "reasoning_effort": "medium"}],
        "source_paths": [source],
        "execution": {"max_attempts": 3},
        "created_at": "2026-08-29T00:00:00Z",
    }
    values.update(overrides)
    return build_campaign_manifest(**values)


def test_manifest_binds_inputs_rubric_sources_and_split(tmp_path: Path) -> None:
    eval_root, source = make_workspace(tmp_path)

    manifest = build(eval_root, source)
    validate_campaign_manifest(manifest)

    assert manifest["dataset"]["membership"]["development"] == ["dev-1"]
    assert manifest["samples"][0]["visible_inputs"][0]["path"] == "task_desc.json"
    assert len(manifest["samples"][0]["evaluator_rubric_sha256"]) == 64
    assert manifest["samples"][0]["evaluator_only"][0]["role"] == "rubric"
    assert manifest["source"]["files"][0]["path"] == "src/component.py"


def test_development_campaign_rejects_holdout_membership(tmp_path: Path) -> None:
    eval_root, source = make_workspace(tmp_path)
    holdout = eval_root / "samples/test-1"
    holdout.mkdir()
    (holdout / "task_desc.json").write_text("{}", encoding="utf-8")
    (holdout / "rubrics.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="contains holdout"):
        build(eval_root, source, sample_ids=["test-1"])


def test_frozen_evaluation_rejects_unsealed_pilot_split(tmp_path: Path) -> None:
    eval_root, source = make_workspace(tmp_path)
    holdout = eval_root / "samples/test-1"
    holdout.mkdir()
    (holdout / "task_desc.json").write_text("{}", encoding="utf-8")
    (holdout / "rubrics.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="sealed paper-final split"):
        build(eval_root, source, mode="frozen-evaluation", sample_ids=["test-1"])


def test_manifest_is_immutable_and_tamper_evident(tmp_path: Path) -> None:
    eval_root, source = make_workspace(tmp_path)
    manifest = build(eval_root, source)
    path = tmp_path / "campaign-manifest.json"

    write_immutable_manifest(path, manifest)
    write_immutable_manifest(path, manifest)
    changed = build(eval_root, source, execution={"max_attempts": 4})
    with pytest.raises(FileExistsError, match="immutable"):
        write_immutable_manifest(path, changed)

    tampered = dict(manifest)
    tampered["campaign_id"] = "tampered"
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_campaign_manifest(tampered)
