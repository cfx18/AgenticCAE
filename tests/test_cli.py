from __future__ import annotations

import sys

import pytest

from cad_evoloop import cli


def test_main_forwards_help_to_geometry_batch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["cad-evoloop", "geometry-batch", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--max-attempts" in output
    assert "--job-time-budget" in output


def test_main_retains_top_level_help(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["cad-evoloop", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert "geometry-report" in capsys.readouterr().out
