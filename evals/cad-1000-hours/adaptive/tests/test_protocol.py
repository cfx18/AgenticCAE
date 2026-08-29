from __future__ import annotations

from pathlib import Path

import pytest

from adaptive.protocol import build_diagnostic, validate_action


def action(**overrides):
    value = {
        "schema_version": "1.0",
        "action": "repair_drawing",
        "owner": "drawing",
        "rationale": "A native entity is missing",
        "evidence": ["D1 failed"],
        "component": None,
        "files": [],
        "instructions": "Add the missing native entity",
        "validation": ["rerun verifier"],
        "expected_outcome": "D1 passes",
        "retryable": True,
    }
    value.update(overrides)
    return value


def test_diagnostic_preserves_typed_exception_checks_and_artifacts(tmp_path: Path) -> None:
    stderr = tmp_path / "stderr.log"
    stderr.write_text(
        "Traceback (most recent call last):\nModuleNotFoundError: No module named 'extract_autocad'\n",
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.dwg"
    candidate.write_bytes(b"dwg")
    diagnostic = build_diagnostic(
        sample_id="s1", run_id="r1", attempt_id="a001",
        stage="verification", component="verifier",
        outcome="infrastructure_error", summary="verifier failed",
        retryable=False, return_code=1, stderr_path=stderr,
        verdict={
            "hard_gates": [{"id": "load", "status": "pass"}],
            "dimensions": [{"id": "D1", "status": "fail"}],
        },
        artifacts=((candidate, "candidate"),),
    )

    assert diagnostic["process"]["exception"]["type"] == "ModuleNotFoundError"
    assert diagnostic["completed_checks"][0]["id"] == "load"
    assert diagnostic["failed_checks"][0]["id"] == "D1"
    assert "retry_verifier" in diagnostic["available_actions"]
    assert diagnostic["artifacts"][0]["sha256"]


def test_diagnostic_redacts_secret_like_fields() -> None:
    diagnostic = build_diagnostic(
        sample_id="s", run_id="r", attempt_id="a", stage="tool",
        component="mcp", outcome="infrastructure_error", summary="failed",
        retryable=True, tool_errors=({"api_token": "secret"},),
    )

    assert diagnostic["tool_errors"][0]["api_token"] == "[REDACTED]"


def test_patch_action_is_limited_to_declared_component_files() -> None:
    allowed = {"prompt": {"prompts/modeling.md"}}
    valid = action(
        action="patch_prompt", owner="prompt", component="prompt",
        files=["prompts/modeling.md"],
    )
    assert validate_action(valid, allowed) == valid

    with pytest.raises(ValueError, match="Unauthorized"):
        validate_action(
            action(action="patch_prompt", owner="prompt", component="prompt", files=["rubrics.json"]),
            allowed,
        )


def test_non_patch_action_cannot_smuggle_file_edits() -> None:
    with pytest.raises(ValueError, match="must not declare"):
        validate_action(action(files=["prompts/modeling.md"]), {"prompt": {"prompts/modeling.md"}})
