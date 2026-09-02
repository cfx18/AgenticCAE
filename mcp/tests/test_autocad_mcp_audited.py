from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cad_evoloop.backends.autocad import audited as AUDITED


def test_redact_hides_secret_fields() -> None:
    assert AUDITED.redact({"api_key": "secret", "command": "LINE"}) == {
        "api_key": "[REDACTED]",
        "command": "LINE",
    }


def test_write_audit_stays_in_workspace(tmp_path: Path, monkeypatch) -> None:
    audit_path = tmp_path / "records" / "mcp.jsonl"
    monkeypatch.setattr(AUDITED, "WORKSPACE", tmp_path)
    monkeypatch.setattr(AUDITED, "AUDIT_PATH", audit_path)
    monkeypatch.setattr(
        AUDITED,
        "RUN_CONTEXT",
        {"sample_id": "sample-1", "run_id": "run-1", "attempt_id": "a001"},
    )

    AUDITED.write_audit(1, "autocad_send_command", {"command": "LINE"}, {"result": {}}, 2.5)

    event = json.loads(audit_path.read_text(encoding="utf-8"))
    assert event["run_id"] == "run-1"
    assert event["tool"] == "autocad_send_command"
    assert event["duration_ms"] == 2.5


def test_configure_server_adds_execution_tools_without_removing_base_tools() -> None:
    base = SimpleNamespace(
        TOOLS={"autocad_send_command": (lambda arguments: arguments, {})},
        com_call=lambda fn: fn(),
        win32com=SimpleNamespace(client=SimpleNamespace(GetActiveObject=lambda progid: progid)),
        pywintypes=SimpleNamespace(com_error=RuntimeError),
    )
    AUDITED.configure_server(base)

    assert "autocad_send_command" in base.TOOLS
    assert {
        "autocad_set_run_context",
        "autocad_start_command",
        "autocad_command_status",
        "autocad_cancel_command",
        "autocad_checkpoint",
        "autocad_core_start",
        "autocad_core_status",
        "autocad_core_cancel",
        "autocad_topology_start",
        "autocad_topology_status",
        "autocad_topology_cancel",
    }.issubset(base.TOOLS)
    start_schema = base.TOOLS["autocad_start_command"][1]
    assert start_schema["properties"]["command"]["description"].startswith(
        "Complete unrestricted"
    )
    assert "operation_manifest" in base.TOOLS["autocad_core_start"][1]["properties"]
    assert "query_source_center" in base.TOOLS["autocad_topology_start"][1]["properties"]
    assert "query_source_center" not in start_schema["properties"]


def test_configure_connection_falls_back_to_versioned_progid(monkeypatch) -> None:
    calls = []

    def get_active_object(progid):
        calls.append(progid)
        if progid == "AutoCAD.Application":
            raise RuntimeError("not registered")
        return "connected"

    base = SimpleNamespace(
        com_call=lambda fn: fn(),
        win32com=SimpleNamespace(client=SimpleNamespace(GetActiveObject=get_active_object)),
        pywintypes=SimpleNamespace(com_error=RuntimeError),
    )
    monkeypatch.setattr(
        AUDITED,
        "autocad_progids",
        lambda: ["AutoCAD.Application", "AutoCAD.Application.24.3"],
    )
    AUDITED.configure_autocad_connection(base)

    assert base.get_app() == "connected"
    assert calls == ["AutoCAD.Application", "AutoCAD.Application.24.3"]
