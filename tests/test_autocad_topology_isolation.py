from __future__ import annotations

import json
from pathlib import Path
import time

from cad_evoloop.backends.autocad import topology


def test_export_process_can_only_rewrite_its_working_copy(tmp_path, monkeypatch):
    original = tmp_path / "candidate.dwg"
    original.write_bytes(b"immutable-submission")
    executable = tmp_path / "accoreconsole.exe"
    executable.touch()
    plugin = tmp_path / "topology.dll"
    plugin.touch()
    output = tmp_path / "topology.json"
    opened = []

    class RewritingProcess:
        pid = 123
        returncode = 0

        def __init__(self, command, **kwargs):
            path = Path(command[command.index("/i") + 1])
            opened.append(path)
            assert path != original
            assert path.read_bytes() == original.read_bytes()
            path.write_bytes(b"rewritten-by-autocad")
            Path(kwargs["env"]["EVOCAD_TOPOLOGY_OUTPUT"]).write_text(
                json.dumps({"source_dwg": str(path), "entities": [], "errors": []}),
                encoding="utf-8",
            )

        def communicate(self, timeout):
            return b"ok", b""

    monkeypatch.setattr(topology.subprocess, "Popen", RewritingProcess)
    manager = topology.TopologyExportJobManager(tmp_path, executable, plugin)
    job = manager.start(str(original), str(output))
    deadline = time.monotonic() + 5
    while job["status"] not in topology.TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])
    assert job["status"] == "succeeded", job
    assert original.read_bytes() == b"immutable-submission"
    assert opened == [Path(job["working_input_path"])]
    assert opened[0].read_bytes() == b"rewritten-by-autocad"
    request = json.loads((Path(job["job_dir"]) / "request.json").read_text())
    assert request["input_path"] == str(original)
    assert request["working_input_path"] == str(opened[0])
