from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cad_evoloop.supervisor.session as MODULE
from cad_evoloop.supervisor import AdaptiveSession


def seed_workspace(root: Path) -> Path:
    eval_root = root / "evals" / "cad-1000-hours"
    for paths in MODULE.SESSION_FILES.values():
        for relative in paths:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("modeling.md"):
                text = "$sample_id $run_id $attempt_id $skill_path $geometry_checkpoint $annotation_checkpoint $candidate"
            elif relative.endswith("repair.md"):
                text = "$sample_id $run_id $attempt_id $previous_candidate $previous_verdict $previous_diagnostic $candidate $reflection"
            else:
                text = "# candidate\n"
            path.write_text(text, encoding="utf-8")
    return eval_root


def valid_stop_action() -> dict:
    return {
        "schema_version": "1.0", "action": "stop", "owner": "harness",
        "rationale": "The failure is not retryable", "evidence": ["exit 1"],
        "component": None, "files": [], "instructions": "",
        "validation": [], "expected_outcome": "preserve evidence", "retryable": False,
    }


def test_session_copies_complete_candidate_components(tmp_path: Path) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)

    assert session.path("src/cad_evoloop/verification/extract_autocad.py").is_file()
    assert session.path(".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py").is_file()
    assert len(session.source_paths()) == sum(len(items) for items in MODULE.SESSION_FILES.values())


def test_planner_output_must_be_available_for_diagnostic(tmp_path: Path, monkeypatch) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output-last-message") + 1])
        value = valid_stop_action()
        value["action"] = "repair_drawing"
        value["owner"] = "drawing"
        output.write_text(json.dumps(value), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    diagnostic = {"available_actions": ["stop"], "outcome": "infrastructure_error"}

    with pytest.raises(ValueError, match="outside diagnostic"):
        session.decide(diagnostic, model="m", effort="medium")


def test_prompt_validation_uses_adaptive_placeholders(tmp_path: Path) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)

    result = session.run_validation("prompt", ["evals/cad-1000-hours/prompts/repair.md"])
    assert result["passed"] is True

    session.path("evals/cad-1000-hours/prompts/repair.md").write_text("$sample_id", encoding="utf-8")
    result = session.run_validation("prompt", ["evals/cad-1000-hours/prompts/repair.md"])
    assert result["passed"] is False


def test_patch_normalizes_windows_bom_before_validation(tmp_path: Path, monkeypatch) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)
    session.manifest["iteration"] = 1
    MODULE.write_json(session.manifest_path, session.manifest)
    (session.root / "decisions" / "i001").mkdir(parents=True)
    target = "src/cad_evoloop/verification/verify.py"

    def fake_run(command, **kwargs):
        if command[1] == "exec":
            session.path(target).write_bytes(b"\xef\xbb\xbfvalue = 1\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    action = {
        **valid_stop_action(),
        "action": "patch_verifier",
        "owner": "verifier",
        "component": "verifier",
        "files": [target],
        "instructions": "repair the import",
    }
    result = session.apply_patch(action, {}, model="m", effort="medium")

    assert result["rolled_back"] is False
    assert session.path(target).read_bytes() == b"value = 1\n"


def test_patch_removes_runtime_caches(tmp_path: Path, monkeypatch) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)
    session.manifest["iteration"] = 1
    MODULE.write_json(session.manifest_path, session.manifest)
    (session.root / "decisions" / "i001").mkdir(parents=True)
    target = "src/cad_evoloop/verification/verify.py"

    def fake_run(command, **kwargs):
        if command[1] == "exec":
            session.path(target).write_text("value = 2\n", encoding="utf-8")
            cache = session.path("src/cad_evoloop/verification/__pycache__/verify.pyc")
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"cache")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    action = {
        **valid_stop_action(),
        "action": "patch_verifier",
        "owner": "verifier",
        "component": "verifier",
        "files": [target],
    }
    result = session.apply_patch(action, {}, model="m", effort="medium")

    assert result["rolled_back"] is False
    assert not session.path("src/cad_evoloop/verification/__pycache__").exists()


def test_boundary_rejection_rolls_back_all_managed_changes(tmp_path: Path, monkeypatch) -> None:
    eval_root = seed_workspace(tmp_path)
    session = AdaptiveSession(eval_root, "s1", create=True)
    session.manifest["iteration"] = 1
    MODULE.write_json(session.manifest_path, session.manifest)
    (session.root / "decisions" / "i001").mkdir(parents=True)
    target = "src/cad_evoloop/verification/verify.py"
    original = session.path(target).read_bytes()

    def fake_run(command, **kwargs):
        session.path(target).write_text("value = 3\n", encoding="utf-8")
        session.path("unauthorized.txt").write_text("bad", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    action = {
        **valid_stop_action(),
        "action": "patch_verifier",
        "owner": "verifier",
        "component": "verifier",
        "files": [target],
    }
    result = session.apply_patch(action, {}, model="m", effort="medium")

    assert result["rolled_back"] is True
    assert "unauthorized" in result["tests"]["errors"][0]
    assert session.path(target).read_bytes() == original
    assert not session.path("unauthorized.txt").exists()
