from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from cad_evoloop.verification import export_core_console


def test_export_lisp_selects_only_model_space_solids(tmp_path) -> None:
    value = export_core_console.export_lisp(tmp_path / "part.stl", tmp_path / "status")

    assert '(0 . "3DSOLID,MESH")' in value
    assert '(410 . "Model")' in value
    assert '"_.STLOUT"' in value
    assert '(setvar "FACETRES" 10)' in value


def test_export_dwg_core_uses_isolation_and_requires_sentinel(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "part.dwg"
    output = tmp_path / "part.stl"
    candidate.write_bytes(b"dwg")
    output.write_bytes(b"stale")
    monkeypatch.setattr(export_core_console, "project_root", lambda: tmp_path)

    def fake_run(command, **kwargs):
        assert "/isolate" in command
        assert not output.exists()
        script = Path(command[command.index("/s") + 1])
        payload_match = re.search(r'\(load "([^"]+)"\)', script.read_text(encoding="utf-8"))
        assert payload_match
        payload = Path(payload_match.group(1))
        status_match = re.search(r'\(open "([^"]+/export\.status)" "w"\)', payload.read_text(encoding="utf-8"))
        assert status_match
        Path(status_match.group(1)).write_text("DONE\n", encoding="utf-8")
        output.write_bytes(b"stl")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(export_core_console.subprocess, "run", fake_run)

    assert export_core_console.export_dwg_core(candidate, output) == output


def test_export_dwg_core_rejects_output_outside_workspace(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    candidate = workspace / "part.dwg"
    candidate.write_bytes(b"dwg")
    monkeypatch.setattr(export_core_console, "project_root", lambda: workspace)

    with pytest.raises(ValueError, match="inside workspace"):
        export_core_console.export_dwg_core(candidate, tmp_path / "outside.stl")
