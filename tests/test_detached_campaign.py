from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from cad_evoloop.evaluation import detached_campaign


def test_worker_records_terminal_state_and_logs(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("", encoding="utf-8")
    control = workspace / "evals/geometry-benchmarks/batch/test/runner"
    control.mkdir(parents=True)
    monkeypatch.setattr(detached_campaign, "project_root", lambda: workspace)
    state = {
        "runner_id": "run-1", "campaign": "test", "status": "running",
        "pid": os.getpid(), "started_at": None,
    }
    (control / "runner-state.json").write_text(json.dumps(state), encoding="utf-8")
    (control / "command.json").write_text(json.dumps({
        "runner_id": "run-1",
        "argv": [sys.executable, "-c", "print('durable output')"],
    }), encoding="utf-8")

    assert detached_campaign.run_worker(control, "run-1") == 0

    final = json.loads((control / "runner-state.json").read_text(encoding="utf-8"))
    assert final["status"] == "completed"
    assert final["return_code"] == 0
    assert "durable output" in (control / "stdout.log").read_text(encoding="utf-8")


def test_status_reports_recorded_and_active_samples(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    campaign = workspace / "evals/geometry-benchmarks/batch/test"
    control = campaign / "runner"
    project = campaign / "projects/sample-2"
    project.mkdir(parents=True)
    control.mkdir(parents=True)
    monkeypatch.setattr(detached_campaign, "project_root", lambda: workspace)
    (control / "runner-state.json").write_text(json.dumps({
        "campaign": "test", "status": "failed", "pid": 99999999,
    }), encoding="utf-8")
    (campaign / "agent-plan.json").write_text(json.dumps({
        "jobs": [{"sample_id": "sample:1"}, {"sample_id": "sample:2"}],
    }), encoding="utf-8")
    (campaign / "agent-results.json").write_text(json.dumps([{
        "sample_id": "sample:1", "work_unit_status": "succeeded", "passed": True,
    }]), encoding="utf-8")
    (project / "state.json").write_text(json.dumps({
        "metadata": {"sample_id": "sample:2"},
        "work_units": {"geometry-reconstruction": {"status": "running"}},
    }), encoding="utf-8")

    status = detached_campaign.campaign_runner_status("test")

    assert status["alive"] is False
    assert status["progress"] == {
        "planned": 2, "recorded": 1, "terminal": 1,
        "strict_passes": 1, "active_samples": ["sample:2"],
    }
