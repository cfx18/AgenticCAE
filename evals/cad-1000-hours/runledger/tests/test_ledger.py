from __future__ import annotations

import json
from pathlib import Path

from runledger import RunLedger


def fixture(tmp_path: Path) -> tuple[RunLedger, Path, Path]:
    workspace = tmp_path / "workspace"
    eval_root = workspace / "evals" / "cad"
    sample = eval_root / "samples" / "sample-1"
    sample.mkdir(parents=True)
    for name in ("task_desc.json", "rubrics.json", "metadata.json"):
        (sample / name).write_text("{}\n", encoding="utf-8")
    source = workspace / "tool.py"
    source.write_text("VERSION = 1\n", encoding="utf-8")
    return RunLedger(eval_root), source, workspace


def test_complete_run_is_queryable_and_integral(tmp_path: Path) -> None:
    ledger, source, workspace = fixture(tmp_path)
    run = ledger.start(
        "sample-1", run_id="run-1", source_paths=[source],
        agent={"system": "codex", "api_key": "should-not-leak"},
    )
    attempt = ledger.add_attempt(run, label="initial geometry")
    candidate = workspace / "candidate.dwg"
    candidate.write_bytes(b"dwg fixture")
    ledger.add_artifact(run, attempt, candidate, role="candidate")
    verdict = workspace / "verdict.json"
    verdict.write_text(
        json.dumps({
            "passed": True, "score": 100.0, "coverage": 80.0,
            "eqc": {"eqc": 75.0, "success": False},
        }),
        encoding="utf-8",
    )
    result = ledger.finish(run, attempt, verdict)

    assert result["status"] == "failed"
    assert result["legacy_status"] == "passed"
    assert result["eqc"] == 75.0
    assert result["eqc_success"] is False
    assert result["evaluation_status"] == "failed"
    assert ledger.verify_integrity(run) == {
        "ok": True,
        "checked_files": 6,
        "events": 5,
        "errors": [],
    }
    listed = ledger.list_runs("sample-1")
    assert listed[0]["run_id"] == "run-1"
    assert listed[0]["score"] == 100.0
    assert listed[0]["eqc"] == 75.0
    assert ledger.show(run)["agent"]["api_key"] == "[REDACTED]"


def test_reindex_recovers_from_deleted_index(tmp_path: Path) -> None:
    ledger, source, _ = fixture(tmp_path)
    ledger.start("sample-1", run_id="run-1", source_paths=[source])
    ledger.index_path.unlink()

    assert ledger.reindex() == 1
    assert ledger.list_runs()[0]["run_id"] == "run-1"


def test_parent_attempt_is_automatic(tmp_path: Path) -> None:
    ledger, source, _ = fixture(tmp_path)
    run = ledger.start("sample-1", run_id="run-1", source_paths=[source])
    first = ledger.add_attempt(run, label="first")
    second = ledger.add_attempt(run, label="second")

    attempts = ledger.show(run)["attempts"]
    assert first == "a001"
    assert second == "a002"
    assert attempts[1]["parent_attempt_id"] == "a001"


def test_reuse_returns_best_verified_candidate(tmp_path: Path) -> None:
    ledger, source, workspace = fixture(tmp_path)
    run = ledger.start("sample-1", run_id="run-1", source_paths=[source])
    attempt = ledger.add_attempt(run, label="verified")
    candidate = workspace / "candidate.dwg"
    candidate.write_bytes(b"reusable drawing")
    ledger.add_artifact(run, attempt, candidate, role="candidate")
    verdict = workspace / "verdict.json"
    verdict.write_text(
        json.dumps({"passed": True, "score": 99.0, "coverage": 90.0}),
        encoding="utf-8",
    )
    ledger.finish(run, attempt, verdict)

    output = workspace / "reuse" / "candidate.dwg"
    reused = ledger.reusable_artifact("sample-1", output=output)
    assert reused["run_id"] == "run-1"
    assert reused["attempt_id"] == "a001"
    assert output.read_bytes() == b"reusable drawing"


def test_integrity_detects_trajectory_tampering(tmp_path: Path) -> None:
    ledger, source, _ = fixture(tmp_path)
    run = ledger.start("sample-1", run_id="run-1", source_paths=[source])
    trajectory = run / "trajectory.jsonl"
    event = json.loads(trajectory.read_text(encoding="utf-8"))
    event["run_id"] = "another-run"
    trajectory.write_text(json.dumps(event) + "\n", encoding="utf-8")

    result = ledger.verify_integrity(run)
    assert result["ok"] is False
    assert any(error["error"] == "run_id mismatch" for error in result["errors"])


def test_mcp_audit_ingestion_is_idempotent(tmp_path: Path) -> None:
    ledger, source, _ = fixture(tmp_path)
    run = ledger.start("sample-1", run_id="run-1", source_paths=[source])
    attempt = ledger.add_attempt(run, label="cad")
    audit = ledger.records_root / "mcp-audit.jsonl"
    audit.write_text(
        json.dumps({
            "event_id": "mcp-1",
            "timestamp": "2026-08-27T12:00:00Z",
            "run_id": "run-1",
            "attempt_id": attempt,
            "tool": "autocad_send_command",
            "status": "pass",
            "duration_ms": 10.0,
            "arguments": {"command": "LINE"},
            "response": {"accepted": True},
        }) + "\n",
        encoding="utf-8",
    )

    assert ledger.ingest_mcp_audit(run) == {"matched": 1, "imported": 1, "duplicates": 0}
    assert ledger.ingest_mcp_audit(run) == {"matched": 1, "imported": 0, "duplicates": 1}


def test_run_diff_reports_source_changes(tmp_path: Path) -> None:
    ledger, source, _ = fixture(tmp_path)
    ledger.start("sample-1", run_id="run-1", source_paths=[source])
    source.write_text("VERSION = 2\n", encoding="utf-8")
    ledger.start("sample-1", run_id="run-2", parent_run_id="run-1", source_paths=[source])

    difference = ledger.diff_runs("run-1", "run-2")
    assert difference["from_run"] == "run-1"
    assert difference["to_run"] == "run-2"
    assert difference["source"]["changed"][0]["path"] == str(source.resolve()).replace("\\", "/")
