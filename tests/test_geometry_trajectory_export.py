import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import pytest


@pytest.fixture
def exporter():
    path = Path(__file__).resolve().parents[1] / "evals/geometry-benchmarks/scripts/export_geometry_trajectory.py"
    spec = importlib.util.spec_from_file_location("geometry_trajectory_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_campaign(root, exporter):
    campaign = root / "campaign"
    job = campaign / "sample/model"
    ledger = root / "records/run"
    attempt = job / "attempts/a001"
    interrupted = attempt / "action-interruptions/i001"
    decision = attempt / "decision-turns/t01"
    for directory in (interrupted, decision, ledger):
        directory.mkdir(parents=True)
    for directory, prompt, events, message in (
        (interrupted, "action-prompt.txt", "codex-events.jsonl", "before interruption"),
        (attempt, "action-prompt.txt", "codex-events.jsonl", "after interruption"),
        (decision, "prompt.txt", "events.jsonl", "stop"),
    ):
        (directory / prompt).write_text("input " + message, encoding="utf-8")
        event = {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": message}}
        (directory / events).write_text(json.dumps(event) + "\n", encoding="utf-8")
    (attempt / "reflection-events.jsonl").write_bytes((decision / "events.jsonl").read_bytes())
    (job / "candidate.dwg").write_bytes(b"binary candidate\x00")
    exporter.write_json(attempt / "geometry-verdict.json", {"score": 100})
    exporter.write_json(campaign / "results.json", [{
        "campaign": "test", "job_dir": str(job), "ledger_run": str(ledger),
        "sample_id": "omnimech:2", "model": "gpt-6-astra", "reasoning_effort": "ultra",
        "score": 100, "passed": True, "selected_attempt_id": "a001", "stop_reason": "strict_pass",
        "attempts": [{"attempt_id": "a001"}],
    }])
    original_job = root / "mcp/jobs/native-test"
    saved = ledger / "artifacts/payload.lsp"
    saved.parent.mkdir()
    saved.write_text("(princ)\n", encoding="utf-8")
    exporter.write_json(ledger / "run.json", {"attempts": [{"artifacts": [{
        "storage": "copy", "stored_path": "artifacts/payload.lsp",
        "source_path": str(original_job / "payload.lsp"), "sha256": exporter.digest(saved),
    }]}]})
    call = {"tool": "autocad_core_start", "status": "pass", "timestamp": "2026-09-15T00:00:00Z",
            "arguments": {"lisp": '(princ "test")', "output_path": str(job / "candidate.dwg")},
            "response": {"result": {"content": [{"type": "text", "text": json.dumps({
                "job_id": "native-test", "job_dir": str(original_job),
            })}]}}}
    (attempt / "mcp-audit.jsonl").write_text(json.dumps(call) + "\n", encoding="utf-8")
    return campaign, job, ledger


def test_export_preserves_phases_raw_bytes_and_immutable_native_job(tmp_path, exporter):
    campaign, job, ledger = fixture_campaign(tmp_path, exporter)
    output = tmp_path / "export"
    result = exporter.export_trial(tmp_path, campaign, output)
    assert result["warnings"] == []
    assert result["counts"]["agent_message"] == 3
    assert result["counts"]["native_jobs"] == 1
    assert exporter.read_json(output / "summary.json")["condition"] == "native-codex"
    events = [json.loads(line) for line in (output / "timeline.jsonl").read_text().splitlines()]
    cli = [row for row in events if row["kind"] == "cli_event"]
    assert [row["phase"] for row in cli] == ["a001/interrupted/i001", "a001/action", "a001/decision/t01"]
    assert len(set((row["phase"], row["payload"]["item"]["id"]) for row in cli)) == 3
    assert (output / "raw/campaign/sample/model/candidate.dwg").read_bytes() == (job / "candidate.dwg").read_bytes()
    assert (output / "autocad/01-candidate/payload.lsp").read_bytes() == (ledger / "artifacts/payload.lsp").read_bytes()
    assert (output / "autocad/01-candidate/agent-input.lsp").read_text() == '(princ "test")'
    manifest = exporter.read_json(output / "manifest.json")
    for item in manifest["files"]:
        assert exporter.digest(output / item["path"]) == item["sha256"]
    with zipfile.ZipFile(result["archive"]) as archive:
        assert archive.testzip() is None
        assert archive.read("raw/campaign/sample/model/candidate.dwg") == (job / "candidate.dwg").read_bytes()


def test_malformed_line_is_preserved_and_reported(tmp_path, exporter):
    campaign, job, _ = fixture_campaign(tmp_path, exporter)
    path = job / "attempts/a001/codex-events.jsonl"
    path.write_bytes(path.read_bytes() + b'{"incomplete":')
    result = exporter.export_trial(tmp_path, campaign, tmp_path / "export")
    assert result["warnings"][0]["line"] == 2
    assert (tmp_path / "export/raw/campaign/sample/model/attempts/a001/codex-events.jsonl").read_bytes() == path.read_bytes()


def test_refuse_overwrite_or_recursive_destination(tmp_path, exporter):
    campaign, _, _ = fixture_campaign(tmp_path, exporter)
    with pytest.raises(ValueError, match="contain one another"):
        exporter.export_trial(tmp_path, campaign, campaign / "export")
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        exporter.export_trial(tmp_path, campaign, output)


def test_reject_altered_ledger_artifact(tmp_path, exporter):
    campaign, _, ledger = fixture_campaign(tmp_path, exporter)
    (ledger / "artifacts/payload.lsp").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        exporter.export_trial(tmp_path, campaign, tmp_path / "export")


def test_reject_native_job_outside_workspace_jobs(tmp_path, exporter):
    campaign, job, _ = fixture_campaign(tmp_path, exporter)
    path = job / "attempts/a001/mcp-audit.jsonl"
    event = json.loads(path.read_text())
    event["response"]["result"]["content"][0]["text"] = json.dumps({
        "job_id": "bad", "job_dir": str(tmp_path.parent),
    })
    path.write_text(json.dumps(event) + "\n")
    with pytest.raises(ValueError, match="Native job path"):
        exporter.export_trial(tmp_path, campaign, tmp_path / "export")


def test_human_diagnostic_does_not_invent_a_model_conversation(tmp_path, exporter):
    campaign, job, _ = fixture_campaign(tmp_path, exporter)
    rows = exporter.read_json(campaign / "results.json")
    rows[0]["stop_reason"] = "human-requested-diagnostic-complete"
    rows.append({**rows[0], "job_dir": str(tmp_path / "another-campaign/model")})
    exporter.write_json(campaign / "results.json", rows)
    attempt = job / "attempts/a001"
    shutil.rmtree(attempt / "action-interruptions")
    shutil.rmtree(attempt / "decision-turns")
    (attempt / "reflection-events.jsonl").unlink()
    exporter.write_json(campaign / "provenance.json", {"agent_model_calls": 0})
    output = tmp_path / "export"
    result = exporter.export_trial(tmp_path, campaign, output)
    summary = exporter.read_json(output / "summary.json")
    assert summary["condition"] == "human-diagnostic"
    assert summary["source_result_rows"] == 2
    assert result["counts"].get("cli_events", 0) == 0
    assert result["counts"]["mcp_audit_calls"] == 0
    assert result["warnings"] == []
