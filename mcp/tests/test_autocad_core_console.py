from __future__ import annotations

from pathlib import Path
import subprocess
import time

import pytest

from mcp import autocad_core_console as core


def wait_for_terminal(manager: core.CoreConsoleJobManager, job_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.status(job_id)
        if job["status"] in core.TERMINAL_STATES:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_decode_console_output_handles_utf16() -> None:
    assert core.decode_console_output("AutoCAD 中文".encode("utf-16-le")) == "AutoCAD 中文"


def test_output_must_stay_inside_workspace(tmp_path: Path) -> None:
    executable = tmp_path / "accoreconsole.exe"
    template = tmp_path / "acadiso.dwt"
    executable.write_bytes(b"exe")
    template.write_bytes(b"dwt")
    manager = core.CoreConsoleJobManager(tmp_path, executable, template)

    with pytest.raises(ValueError, match="inside workspace"):
        manager.start("(princ)", str(tmp_path.parent / "outside.dwg"))


def test_success_requires_save_sentinel(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "accoreconsole.exe"
    template = tmp_path / "acadiso.dwt"
    executable.write_bytes(b"exe")
    template.write_bytes(b"seed")

    class FakeProcess:
        pid = 123
        returncode = 0

        def __init__(self, args, **kwargs):
            self.script = Path(args[4])

        def communicate(self, timeout=None):
            (self.script.parent / "success.txt").write_text("ok\n", encoding="utf-8")
            return b"done", b""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def kill(self):
            self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    manager = core.CoreConsoleJobManager(tmp_path, executable, template)
    output = tmp_path / "result.dwg"
    job = manager.start("(princ)", str(output))

    finished = wait_for_terminal(manager, job["job_id"])
    assert finished["status"] == "succeeded"
    assert output.read_bytes() == b"seed"
    assert (Path(finished["job_dir"]) / "stdout.log").read_text(encoding="utf-8") == "done"


def test_operation_manifest_is_durable_but_does_not_change_lisp(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "accoreconsole.exe"
    template = tmp_path / "acadiso.dwt"
    executable.write_bytes(b"exe")
    template.write_bytes(b"seed")

    class FakeProcess:
        pid = 124
        returncode = 0

        def __init__(self, args, **kwargs):
            self.script = Path(args[4])

        def communicate(self, timeout=None):
            (self.script.parent / "success.txt").write_text("ok\n", encoding="utf-8")
            return b"done", b""

        def poll(self): return self.returncode
        def terminate(self): self.returncode = 1
        def kill(self): self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    manager = core.CoreConsoleJobManager(tmp_path, executable, template)
    manifest = [{"operation_id": "op-hole", "intent": "subtract through hole"}]
    job = manager.start("(command \"_.BOX\")", str(tmp_path / "out.dwg"), operation_manifest=manifest)
    finished = wait_for_terminal(manager, job["job_id"])
    request = __import__("json").loads((Path(finished["job_dir"]) / "request.json").read_text())
    assert request["operation_manifest"] == manifest
    recorded = finished["operation_manifest"][0]
    assert recorded["operation_id"] == "op-hole"
    assert recorded["observed_entity_handles"] == []
    assert recorded["mcp_job_id"] == finished["job_id"]
    assert recorded["input_path"] == str(template)
    assert recorded["output_path"] == str(tmp_path / "out.dwg")
    assert recorded["topology_before_path"] is None
    assert recorded["topology_after_path"] is None
    assert '(command "_.BOX")' in (Path(finished["job_dir"]) / "payload.lsp").read_text()


def test_boolean_lineage_capture_wraps_unrestricted_lisp_with_native_snapshots(
    tmp_path: Path, monkeypatch,
) -> None:
    executable = tmp_path / "accoreconsole.exe"
    template = tmp_path / "acadiso.dwt"
    plugin = tmp_path / "EvoCadTopology.dll"
    for path, value in ((executable, b"exe"), (template, b"seed"), (plugin, b"dll")):
        path.write_bytes(value)

    class FakeProcess:
        pid = 125
        returncode = 0

        def __init__(self, args, **kwargs):
            self.script = Path(args[4])
            self.environment = kwargs["env"]

        def communicate(self, timeout=None):
            (self.script.parent / "success.txt").write_text("ok\n", encoding="utf-8")
            for key in ("EVOCAD_LINEAGE_BEFORE_OUTPUT", "EVOCAD_LINEAGE_AFTER_OUTPUT"):
                Path(self.environment[key]).write_text(
                    '{"schema_version":"1.0","entities":[],"errors":[]}\n', encoding="utf-8",
                )
            return b"done", b""

        def poll(self): return self.returncode
        def terminate(self): self.returncode = 1
        def kill(self): self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    manager = core.CoreConsoleJobManager(
        tmp_path, executable, template, topology_plugin=plugin,
    )
    manifest = [{"operation_id": "op-hole", "intent": "subtract through hole"}]
    job = manager.start("(command \"_.SUBTRACT\")", str(tmp_path / "out.dwg"), operation_manifest=manifest)
    finished = wait_for_terminal(manager, job["job_id"])

    script = (Path(finished["job_dir"]) / "run.scr").read_text(encoding="utf-8")
    assert script.index("EVOCAD_EXPORT_LINEAGE_BEFORE") < script.index("payload.lsp")
    assert script.index("payload.lsp") < script.index("EVOCAD_EXPORT_LINEAGE_AFTER")
    assert finished["boolean_lineage_capture"]["status"] == "succeeded"
    recorded = finished["operation_manifest"][0]
    assert Path(recorded["topology_before_path"]).is_file()
    assert Path(recorded["topology_after_path"]).is_file()
