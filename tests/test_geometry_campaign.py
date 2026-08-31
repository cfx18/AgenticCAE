from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def _geometry_result(score: float) -> dict:
    return {
        "passed": False,
        "quality_tier": "failed",
        "score": score,
        "coverage": 100.0,
        "checks": {
            "candidate_watertight": True,
            "voxel_iou": False,
            "normalized_chamfer": False,
            "bbox_relative_error": False,
            "volume_relative_error": False,
        },
        "acceptable_checks": {
            "candidate_watertight": True,
            "voxel_iou": False,
            "normalized_chamfer": False,
            "bbox_relative_error": False,
            "volume_relative_error": False,
        },
        "metrics": {
            "voxel_iou": score / 100,
            "normalized_chamfer": 0.02,
            "bbox_relative_error": 0.1,
            "volume_relative_error": 0.1,
        },
        "mismatch": {},
        "candidate_geometry": {"watertight": True, "extents": [10, 10, 10]},
        "ground_truth_geometry": {"watertight": True, "extents": [10, 10, 10]},
        "alignment": {"scale_allowed": False},
    }


def _run_closed_loop_job(
    tmp_path: Path,
    monkeypatch,
    *,
    decisions: list[str],
    max_iterations: int,
) -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _manifest(workspace / ".local/data")
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    monkeypatch.setattr(geometry_campaign, "_source_paths", lambda _workspace: [])
    monkeypatch.setattr(geometry_campaign, "_prompt", lambda *args, **kwargs: "action")
    monkeypatch.setattr(geometry_campaign, "_decision_prompt", lambda *args, **kwargs: "decision")

    def initial_command(_exe, _model, _effort, job_dir, _images, _prompt, _audit, final_path):
        attempt_id = final_path.parent.name
        return ["action", str(job_dir / f"candidate.{attempt_id}.dwg")]

    def resume_command(
        _exe, _model, _effort, job_dir, _thread, _prompt, final_path,
        *, with_autocad, **_kwargs,
    ):
        if with_autocad:
            attempt_id = final_path.parent.name
            return ["action", str(job_dir / f"candidate.{attempt_id}.dwg")]
        return ["decision", str(final_path)]

    pending = list(decisions)

    def run_process(command, *, events_path, stderr_path, **_kwargs):
        events_path.write_text(
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}) + "\n"
            + json.dumps({
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }) + "\n",
            encoding="utf-8",
        )
        stderr_path.write_text("", encoding="utf-8")
        if command[0] == "action":
            Path(command[1]).write_bytes(b"dwg")
        else:
            choice = pending.pop(0)
            Path(command[1]).write_text(json.dumps({
                "schema_version": "1.0",
                "failure_owner": "drawing",
                "observed_failures": ["Mismatch remains"],
                "root_causes": ["Feature is incomplete"],
                "structure_assessment": "The current structure can still be improved.",
                "can_improve": choice == "continue",
                "decision": choice,
                "decision_reason": f"Agent chose {choice} after reading this iteration verdict.",
                "planned_geometry_changes": ["Repair the missing feature"] if choice == "continue" else [],
                "system_change_proposal": None,
                "expected_score_gain": 10 if choice == "continue" else None,
                "confidence": 0.8,
            }), encoding="utf-8")
        return 0, False

    score_values = iter(40.0 + 10.0 * index for index in range(max_iterations))

    def export_candidate(_candidate, output, timeout=None):
        Path(output).write_bytes(b"stl")
        return Path(output)

    monkeypatch.setattr(geometry_campaign, "codex_command", initial_command)
    monkeypatch.setattr(geometry_campaign, "codex_resume_command", resume_command)
    monkeypatch.setattr(geometry_campaign, "_run_codex_process", run_process)
    monkeypatch.setattr(geometry_campaign, "export_dwg_core", export_candidate)
    monkeypatch.setattr(
        geometry_campaign,
        "score_geometry_files",
        lambda *_args, **_kwargs: _geometry_result(next(score_values)),
    )
    return geometry_campaign.run_geometry_job(
        manifest_path=manifest,
        sample=_sample(),
        campaign="closed-loop",
        model="test-model",
        effort="medium",
        executable="codex",
        timeout=300,
        max_iterations=max_iterations,
        stagnation_limit=2,
        job_time_budget=3600,
        score_samples=100,
        voxel_resolution=16,
    )


def test_agent_feedback_decision_controls_the_next_iteration(tmp_path, monkeypatch) -> None:
    result = _run_closed_loop_job(
        tmp_path,
        monkeypatch,
        decisions=["continue", "stop"],
        max_iterations=5,
    )

    assert len(result["attempts"]) == 2
    assert [attempt["agent_decision"] for attempt in result["attempts"]] == [
        "continue", "stop",
    ]
    assert result["stop_reason"] == "agent_stop"
    assert result["agent_requested_continue"] is False
    assert {attempt["thread_id"] for attempt in result["attempts"]} == {"thread-1"}
    assert result["attempts"][0]["usage"]["input_tokens"] == 20
    assert result["attempts"][0]["usage"]["output_tokens"] == 4
    job_dir = Path(result["job_dir"])
    assert (job_dir / "attempts/a001/reflection.json").is_file()
    feedback = json.loads((job_dir / "attempts/a001/feedback-packet.json").read_text())
    assert feedback["verdict"]["score"] == 40.0
    assert feedback["trajectory_state"]["iteration"] == 1
    assert (job_dir / "attempts/a002/reflection-events.jsonl").is_file()


def test_max_iterations_is_a_safety_stop_after_agent_feedback(tmp_path, monkeypatch) -> None:
    result = _run_closed_loop_job(
        tmp_path,
        monkeypatch,
        decisions=["continue", "continue"],
        max_iterations=2,
    )

    assert len(result["attempts"]) == 2
    final_attempt = result["attempts"][-1]
    assert final_attempt["agent_decision"] == "continue"
    assert final_attempt["can_improve"] is True
    assert final_attempt["safety_stop_reason"] == "max_iterations"
    assert result["stop_reason"] == "max_iterations"
    assert result["agent_requested_continue"] is True


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
    assert campaign["agent_loop_protocol"] == "evocad-agent-loop-v2"
    assert campaign["execution"]["feedback_turn_required"] is True
    assert campaign["execution"]["agent_controls_continuation"] is True


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


def test_geometry_campaign_aborts_after_repeated_agent_start_failures(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _manifest(workspace / ".local/data")
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    calls = []

    def fail_start(**kwargs):
        calls.append(kwargs["model"])
        return {
            "sample_id": kwargs["sample"]["sample_id"],
            "model": kwargs["model"],
            "passed": False,
            "score": 0.0,
            "stop_reason": "decision_unavailable",
            "attempts": [{"thread_id": None, "return_code": 1}],
        }

    monkeypatch.setattr(geometry_campaign, "run_geometry_job", fail_start)

    with pytest.raises(RuntimeError, match="three consecutive Codex agent startup failures"):
        geometry_campaign.run_geometry_campaign(
            manifest,
            campaign="startup-failure",
            models=["m1", "m2", "m3", "m4"],
            executable="codex",
        )

    assert calls == ["m1", "m2", "m3"]


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
    assert "--ephemeral" not in command


def test_codex_resume_keeps_thread_and_separates_feedback_from_cad(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: workspace)
    action = geometry_campaign.codex_resume_command(
        "codex", "model", "medium", tmp_path, "thread-1", "repair",
        tmp_path / "final.txt", with_autocad=True, audit_path=tmp_path / "audit.jsonl",
    )
    decision = geometry_campaign.codex_resume_command(
        "codex", "model", "medium", tmp_path, "thread-1", "judge",
        tmp_path / "reflection.json", with_autocad=False,
        output_schema=tmp_path / "decision.schema.json",
    )

    assert "resume" in action and "thread-1" in action
    assert "mcp_servers.autocad.command=\"python\"" in action
    assert "resume" in decision and "thread-1" in decision
    assert not any("mcp_servers.autocad" in value for value in decision)
    assert "--output-schema" in decision


def test_agent_decision_schema_declares_types_for_structured_output() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "src/cad_evoloop/evaluation/schemas/geometry-agent-decision.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert all("type" in value for value in schema["properties"].values())


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


def test_safety_stop_does_not_treat_stagnation_as_an_automatic_stop() -> None:
    assert geometry_campaign.safety_stop_reason(
        passed=False, iteration=3, max_iterations=12,
        elapsed_seconds=100, job_time_budget=3600,
    ) is None
    assert geometry_campaign.safety_stop_reason(
        passed=False, iteration=12, max_iterations=12,
        elapsed_seconds=100, job_time_budget=3600,
    ) == "max_iterations"
    assert geometry_campaign.safety_stop_reason(
        passed=False, iteration=3, max_iterations=12,
        elapsed_seconds=3600, job_time_budget=3600,
    ) == "job_time_budget"
    assert geometry_campaign.safety_stop_reason(
        passed=True, iteration=1, max_iterations=12,
        elapsed_seconds=10, job_time_budget=3600,
    ) == "strict_pass"


def test_feedback_diagnostics_exposes_nested_backend_failure(tmp_path) -> None:
    events = {"errors": ["turn warning"]}
    audit = tmp_path / "mcp-audit.jsonl"
    stderr = tmp_path / "stderr.log"
    audit.write_text(json.dumps({
        "tool": "autocad_core_status",
        "status": "pass",
        "duration_ms": 2.5,
        "response": {"result": {"content": [{"text": json.dumps({
            "job_id": "job-1",
            "status": "timed_out",
            "return_code": 1,
            "error": "Core Console exceeded 120 seconds",
        })}]}},
    }) + "\n", encoding="utf-8")
    stderr.write_text("connection warning\n", encoding="utf-8")

    diagnostics = geometry_campaign._feedback_diagnostics(events, audit, stderr)

    assert diagnostics["codex_errors"] == ["turn warning"]
    assert diagnostics["mcp_calls"][0]["transport_status"] == "pass"
    assert diagnostics["mcp_calls"][0]["backend_result"]["status"] == "timed_out"
    assert diagnostics["stderr_tail"] == ["connection warning"]


def test_agent_decision_validation_requires_coherent_continuation() -> None:
    with pytest.raises(ValueError, match="planned geometry or recovery action"):
        geometry_campaign._validate_agent_decision({
            "decision": "continue",
            "can_improve": True,
            "planned_geometry_changes": [],
            "expected_score_gain": 10,
        })


def test_attempt_timeout_is_bounded_by_remaining_job_budget() -> None:
    assert geometry_campaign.remaining_attempt_timeout(1800, 2400.0) == 1800
    assert geometry_campaign.remaining_attempt_timeout(1800, 37.9) == 37
    assert geometry_campaign.remaining_attempt_timeout(1800, -1.0) == 1
