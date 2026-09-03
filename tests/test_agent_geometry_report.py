from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.evaluation.agent_geometry_report import (
    _load_baseline_results,
    compare_sol_campaigns,
    materialize_agent_campaign,
    render_agent_evaluation_figure,
    summarize_long_horizon_outcomes,
)


def result(sample: str, score: float, passed: bool, root: Path) -> dict:
    return {
        "campaign": "agent-test",
        "sample_id": sample,
        "model": "gpt-5.6-sol",
        "score": score,
        "passed": passed,
        "selected_attempt_id": "a001",
        "job_dir": str(root / sample.replace(":", "-")),
        "attempts": [{
            "attempt_id": "a001", "attempt_number": 1, "score": score,
            "passed": passed, "elapsed_seconds": 10,
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }],
    }


def test_materializes_results_in_frozen_plan_order(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    manifest = {
        "protocol": "evocad-agent-geometry-v1",
        "agent_condition": "durable-kernel-compat-v1",
        "campaign_id": "agent-test",
        "model": {"name": "gpt-5.6-sol", "reasoning_effort": "medium"},
        "source_manifest_sha256": "a" * 64,
        "execution": {},
        "selection": {
            "path": "selection.json", "selection_sha256": "b" * 64, "sample_count": 2,
        },
        "runtime_environment": {},
        "campaign_manifest_sha256": "c" * 64,
    }
    (campaign / "agent-campaign-manifest.json").write_text(json.dumps(manifest))
    (campaign / "agent-plan.json").write_text(json.dumps({
        "jobs": [{"sample_id": "sample:2"}, {"sample_id": "sample:1"}],
    }))
    entries = []
    for sample in ("sample:1", "sample:2"):
        path = campaign / sample.replace(":", "-") / "result.json"
        path.parent.mkdir()
        path.write_text(json.dumps(result(sample, 90, False, campaign)))
        entries.append({"sample_id": sample, "result": str(path)})
    (campaign / "agent-results.json").write_text(json.dumps(entries))

    value = materialize_agent_campaign(campaign)

    assert [row["sample_id"] for row in value["results"]] == ["sample:2", "sample:1"]
    assert value["provenance"]["complete"] is True
    assert set(value["provenance"]["report_source_hashes"]) == {
        "agent_geometry_report.py", "geometry_report.py",
    }
    assert json.loads((campaign / "campaign-manifest.json").read_text())["models"][0]["name"] == "gpt-5.6-sol"
    assert [row["sample_id"] for row in _load_baseline_results(campaign)] == [
        "sample:2", "sample:1",
    ]


def test_loads_baseline_from_report_snapshot(tmp_path: Path) -> None:
    report = tmp_path / "report"
    report.mkdir()
    expected = [result("sample:1", 91, False, tmp_path)]
    (report / "results.json").write_text(json.dumps(expected), encoding="utf-8")

    assert _load_baseline_results(report) == expected


def test_materialization_records_human_block_without_fabricating_result(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    manifest = {
        "protocol": "evocad-agent-geometry-v1",
        "agent_condition": "durable-kernel-human-feedback-v1",
        "campaign_id": "feedback-test",
        "model": {"name": "gpt-5.6-sol", "reasoning_effort": "medium"},
        "source_manifest_sha256": "a" * 64,
        "execution": {},
        "selection": {
            "path": "selection.json", "selection_sha256": "b" * 64,
            "sample_count": 2,
        },
        "runtime_environment": {},
        "campaign_manifest_sha256": "c" * 64,
    }
    (campaign / "agent-campaign-manifest.json").write_text(json.dumps(manifest))
    (campaign / "agent-plan.json").write_text(json.dumps({
        "jobs": [{"sample_id": "sample:1"}, {"sample_id": "sample:2"}],
    }))
    result_path = campaign / "sample-1/result.json"
    result_path.parent.mkdir()
    result_path.write_text(json.dumps(result("sample:1", 90, False, campaign)))
    (campaign / "agent-results.json").write_text(json.dumps([
        {"sample_id": "sample:1", "result": str(result_path)},
        {
            "sample_id": "sample:2",
            "result": None,
            "project_id": "sample-2",
            "project_status": "active",
            "work_unit_status": "blocked",
            "stop_reason": "human_clarification_required",
            "clarification_questions": ["What is the first step height?"],
            "project_integrity": {"ok": True},
        },
    ]))

    value = materialize_agent_campaign(campaign)

    assert [row["sample_id"] for row in value["results"]] == ["sample:1"]
    assert value["provenance"]["complete"] is False
    assert value["provenance"]["blocked_work_units"] == [{
        "sample_id": "sample:2",
        "project_id": "sample-2",
        "project_status": "active",
        "work_unit_status": "blocked",
        "stop_reason": "human_clarification_required",
        "clarification_questions": ["What is the first step height?"],
        "project_integrity": {"ok": True},
    }]


def test_compares_only_paired_sol_samples(tmp_path: Path) -> None:
    candidate = [result("sample:1", 100, True, tmp_path), result("sample:2", 80, False, tmp_path)]
    baseline = [result("sample:1", 90, False, tmp_path), result("sample:3", 100, True, tmp_path)]

    comparison = compare_sol_campaigns(candidate, baseline)

    assert comparison["paired_samples"] == 1
    assert comparison["baseline_campaign"] == "agent-test"
    assert comparison["candidate_campaign"] == "agent-test"
    assert comparison["strict_pass_gains"] == 1
    assert comparison["mean_score_delta"] == 10
    assert comparison["pairs"][0]["sample_id"] == "sample:1"


def test_summarizes_safety_censoring_and_checkpoint_rollback(tmp_path: Path) -> None:
    run = result("sample:1", 80, False, tmp_path)
    run["attempts"].append({
        "attempt_id": "a002", "attempt_number": 2, "score": 70,
        "passed": False, "elapsed_seconds": 10,
    })
    run.update({
        "selected_attempt_id": "a001",
        "stop_reason": "max_iterations",
        "agent_requested_continue": True,
        "integrity": {"ok": True},
    })

    summary = summarize_long_horizon_outcomes([run])

    assert summary["safety_censored_runs"] == 1
    assert summary["safety_censored_sample_ids"] == ["sample:1"]
    assert summary["best_checkpoint_rollbacks"] == 1
    assert summary["by_dataset"] == [{
        "dataset": "sample",
        "runs": 1,
        "strict_passes": 0,
        "strict_pass_rate": 0.0,
        "first_attempt_mean": 80.0,
        "selected_mean": 80.0,
        "mean_attempts": 2,
        "safety_censored_runs": 1,
    }]


def test_summarizes_unavailable_reflection_as_runtime_censoring(tmp_path: Path) -> None:
    run = result("sample:2", 99.2, False, tmp_path)
    run.update({
        "stop_reason": "decision_unavailable",
        "agent_requested_continue": False,
        "integrity": {"ok": True},
    })

    summary = summarize_long_horizon_outcomes([run])

    assert summary["autonomous_stops"] == 0
    assert summary["safety_censored_runs"] == 0
    assert summary["runtime_censored_runs"] == 1
    assert summary["runtime_censored_sample_ids"] == ["sample:2"]


def test_renders_fixed_model_agent_evaluation_figure(tmp_path: Path) -> None:
    first = result("omnimech:1", 60, False, tmp_path)
    first["stop_reason"] = "agent_stop"
    first["integrity"] = {"ok": True}
    second = result("ortho2cad:1", 100, True, tmp_path)
    second["stop_reason"] = "strict_pass"
    second["integrity"] = {"ok": True}
    results = [first, second]
    trajectory = summarize_long_horizon_outcomes(results)
    campaign = {
        "runs": 2, "pass_at_1": 1, "strict_passes": 1,
        "first_attempt_mean": 80.0, "selected_mean": 80.0,
    }

    image = render_agent_evaluation_figure(results, campaign, trajectory)

    assert image.size == (1800, 1100)
