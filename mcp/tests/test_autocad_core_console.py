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
