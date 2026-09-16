from __future__ import annotations

from pathlib import Path

import pytest

from cad_evoloop.posttrain.dataset_families import (
    load_registry,
    summarize_kimi_runs,
    validate_registry,
    workspace_path,
)


def test_dataset_family_registry_is_valid_and_bound_to_workspace():
    registry = load_registry()
    summary_path = Path("evals/data/posttrain/multifamily-seed-r1/dataset-summary.json")
    if not summary_path.exists():
        pytest.skip("local evals/data artifacts are stored out-of-band")
    summary = validate_registry(registry, check_existing=True)
    assert summary["families"] >= 6
    assert summary["status_counts"]["active_seeded"] >= 1
    assert summary["available_artifacts_checked"] >= 8


def test_dataset_family_sample_goals_are_small_pilot_batches():
    registry = load_registry()
    goals = {row["family_id"]: row["pilot_sample_goal"] for row in registry["families"]}
    assert all(20 <= value <= 30 for value in goals.values())
    assert goals["cad_vqa_real_drawing"] == 20
    assert goals["assembly_spec_to_cad"] == 20


def test_workspace_path_rejects_escape():
    try:
        workspace_path("../outside")
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("Expected workspace escape to be rejected")


def test_existing_kimi_smoke_summary_counts():
    summary = summarize_kimi_runs([".local/posttrain/kimi-smoke-r3/summary.json"])
    assert summary["attempted"] == 14
    assert summary["graded"] == 13
    assert summary["passed"] == 13
    assert summary["timeouts"] == 1
