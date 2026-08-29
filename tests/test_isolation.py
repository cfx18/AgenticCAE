from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation.isolation import (
    assert_isolated_agent_bundle,
    export_agent_inputs,
    find_forbidden_event_references,
    input_inventory,
)


def make_sample(path: Path) -> Path:
    path.mkdir()
    (path / "task_desc.json").write_text(json.dumps({"task": "draw"}), encoding="utf-8")
    (path / "rubrics.json").write_text("{}", encoding="utf-8")
    (path / "metadata.json").write_text("{}", encoding="utf-8")
    (path / "input_files").mkdir()
    (path / "input_files/reference.png").write_bytes(b"reference")
    (path / "output_files").mkdir()
    (path / "output_files/answer.dwg").write_bytes(b"answer")
    return path


def test_export_contains_only_declared_agent_inputs(tmp_path: Path) -> None:
    sample = make_sample(tmp_path / "sample")
    destination = tmp_path / "job"

    inventory = export_agent_inputs(sample, destination)

    assert [item["path"] for item in inventory] == [
        "task_desc.json", "input_files/reference.png",
    ]
    assert input_inventory(sample) == inventory
    assert (destination / "task_desc.json").is_file()
    assert (destination / "input_files/reference.png").is_file()
    assert not (destination / "rubrics.json").exists()
    assert not (destination / "metadata.json").exists()
    assert not (destination / "output_files").exists()


def test_bundle_audit_rejects_undeclared_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "task_desc.json").write_text("{}", encoding="utf-8")
    (bundle / "rubrics.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Evaluator-only asset leaked"):
        assert_isolated_agent_bundle(bundle)


def test_event_audit_flags_evaluator_asset_references() -> None:
    assert find_forbidden_event_references("opened rubrics.json from /samples/id/") == [
        "/samples/", "rubrics.json",
    ]
