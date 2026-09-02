from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

import pytest

from mcp import autocad_topology as topology


def wait(manager, job_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.status(job_id)
        if job["status"] in topology.TERMINAL_STATES:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_topology_export_is_workspace_bounded_and_reports_counts(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "accoreconsole.exe"
    plugin = tmp_path / "EvoCadTopology.dll"
    source = tmp_path / "candidate.dwg"
    query_input = tmp_path / "query.tsv"
    for path in (executable, plugin, source):
        path.write_bytes(b"x")
    query_input.write_text("region-1#00\t0\t0\t0\n", encoding="utf-8")

    class FakeProcess:
        pid = 125
        returncode = 0

        def __init__(self, args, **kwargs):
            self.output = Path(kwargs["env"]["EVOCAD_TOPOLOGY_OUTPUT"])
            self.query_output = Path(kwargs["env"]["EVOCAD_FACE_QUERY_OUTPUT"])

        def communicate(self, timeout=None):
            self.output.write_text(json.dumps({"schema_version": "1.0", "entities": [{}], "errors": []}))
            self.query_output.write_text(json.dumps({"schema_version": "1.0", "queries": [{}]}))
            return b"EVOCAD_TOPOLOGY_OK", b""

        def poll(self): return self.returncode
        def terminate(self): self.returncode = 1
        def kill(self): self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    manager = topology.TopologyExportJobManager(tmp_path, executable, plugin)
    job = manager.start(
        str(source), str(tmp_path / "topology.json"),
        query_input_path=str(query_input), query_output_path=str(tmp_path / "query.json"),
    )
    finished = wait(manager, job["job_id"])
    assert finished["status"] == "succeeded"
    assert finished["entity_count"] == 1
    assert finished["export_error_count"] == 0
    assert finished["query_count"] == 1
    with pytest.raises(ValueError, match="inside workspace"):
        manager.start(str(source), str(tmp_path.parent / "outside.json"))
