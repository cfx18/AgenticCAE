from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def native():
    path = Path(__file__).resolve().parents[1] / "evals/cadgenbench/scripts/run_native_autocad.py"
    spec = importlib.util.spec_from_file_location("cadgenbench_native_autocad", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_preserves_autocad_and_blind_generation(native, tmp_path):
    prompt = native.task_prompt(tmp_path, tmp_path / "task", "111", "fixture-111")
    assert "locally installed AutoCAD" in prompt
    assert "Do not use CadQuery, build123d" in prompt
    assert "There is no prescribed IR or external repair loop" in prompt
    assert "Do not invent an accuracy score" in prompt
    assert "Do not publish or upload" in prompt
    assert "leave the user's desktop drawings untouched" in prompt
    assert "outputs/candidate.dwg" in prompt


def test_prepare_has_no_gt_and_detects_modified_input(native, tmp_path, monkeypatch):
    source = tmp_path / "evals/cadgenbench/inputs/111"
    source.mkdir(parents=True)
    (source / "input.png").write_bytes(b"drawing")
    (source / "description.yaml").write_text("description: reproduce drawing")
    (source / "ground_truth.step").write_bytes(b"must-not-stage")
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"mock")
    monkeypatch.setattr(native, "project_root", lambda: tmp_path)
    monkeypatch.setattr(native.subprocess, "check_output", lambda *a, **k: "mock-cli")
    args = ["trial", "--campaign", "fixture", "--executable", str(executable)]
    monkeypatch.setattr(sys, "argv", [*args, "--prepare-only"])
    native.main()
    task = tmp_path / "evals/cadgenbench/runs/fixture"
    record = json.loads((task / "run.json").read_text())
    command = json.loads((task / "attempts/a001/command.json").read_text())["argv"]
    assert record["state"] == "prepared"
    assert record["official_score"] is None
    assert record["model"] == "gpt-6-astra" and record["effort"] == "ultra"
    assert not list(task.rglob("*.step"))
    assert command[command.index("--model") + 1] == "gpt-6-astra"
    assert 'model_reasoning_effort="ultra"' in command
    assert "--approve-for-me" in command
    with pytest.raises(FileExistsError):
        native.main()
    (task / "input/input.png").write_bytes(b"changed")
    monkeypatch.setattr(sys, "argv", [*args, "--execute-prepared"])
    with pytest.raises(ValueError, match="Prepared input changed"):
        native.main()


def test_inventory_is_hashed_and_excludes_mutable_state(native, tmp_path):
    (tmp_path / "candidate.dwg").write_bytes(b"candidate")
    (tmp_path / "run.json").write_text("{}")
    (tmp_path / "result.json").write_text("{}")
    rows = native.inventory(tmp_path)
    assert len(rows) == 1
    assert rows[0]["path"] == "candidate.dwg"
    assert rows[0]["sha256"] == native.sha256_file(tmp_path / "candidate.dwg")


def test_archive_preserves_native_jobs_and_recovers_only_finished_record(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "evals/cadgenbench/scripts/archive_native_run.py"
    spec = importlib.util.spec_from_file_location("cadgenbench_archive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "project_root", lambda: tmp_path)
    task = tmp_path / "evals/cadgenbench/runs/fixture"
    attempt = task / "attempts/a001"
    attempt.mkdir(parents=True)
    (task / "run.json").write_text(json.dumps({"state": "running"}))
    with pytest.raises(ValueError, match="active run"):
        module.archive(task)
    (task / "run.json").write_text(json.dumps({
        "state": "generation_ready_for_review", "sample_id": "cadgenbench:111",
        "model": "gpt-6-astra", "effort": "ultra", "elapsed_seconds": 12,
    }))
    job = tmp_path / "mcp/jobs/example"
    job.mkdir(parents=True)
    (job / "payload.lsp").write_text("(princ)")
    (attempt / "codex-events.jsonl").write_text(json.dumps({
        "type": "thread.started", "thread_id": "fixture-thread",
    }) + "\n")
    (attempt / "action-prompt.txt").write_text("Use the drawing")
    (attempt / "mcp-audit.jsonl").write_text(json.dumps({
        "tool": "autocad_core_start", "response": {"result": {"content": [{
            "type": "text", "text": json.dumps({"job_dir": str(job)}),
        }]}},
    }) + "\n")
    result = module.archive(task)
    assert result["native_jobs"] == 1
    assert (task / "recorded-execution/autocad/example/payload.lsp").read_text() == "(princ)"
    recovered = json.loads((task / "result.json").read_text())
    assert recovered["official_score"] is None
    assert recovered["return_code"] == 0
    assert "No model/CAD rerun" in recovered["record_recovery"]
    with pytest.raises(FileExistsError):
        module.archive(task)
