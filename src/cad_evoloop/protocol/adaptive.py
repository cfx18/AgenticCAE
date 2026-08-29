"""Typed observations and decisions for the adaptive CAD control loop."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import uuid


SCHEMA_VERSION = "1.0"
OWNERS = ("drawing", "prompt", "skill", "mcp", "verifier", "task", "harness")
ALLOWED_ACTIONS = (
    "repair_drawing",
    "retry_verifier",
    "retry_tool",
    "restart_mcp",
    "patch_prompt",
    "patch_skill",
    "patch_mcp",
    "patch_verifier",
    "add_test",
    "stop",
)
PATCH_COMPONENT = {
    "patch_prompt": "prompt",
    "patch_skill": "skill",
    "patch_mcp": "mcp",
    "patch_verifier": "verifier",
}
SECRET_KEYS = ("authorization", "cookie", "password", "secret", "token", "api_key", "apikey")

ACTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "action", "owner", "rationale", "evidence",
        "component", "files", "instructions", "validation",
        "expected_outcome", "retryable",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": SCHEMA_VERSION},
        "action": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
        "owner": {"type": "string", "enum": list(OWNERS)},
        "rationale": {"type": "string", "minLength": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "component": {"type": ["string", "null"], "enum": [None, "prompt", "skill", "mcp", "verifier", "test"]},
        "files": {"type": "array", "items": {"type": "string"}},
        "instructions": {"type": "string"},
        "validation": {"type": "array", "items": {"type": "string"}},
        "expected_outcome": {"type": "string", "minLength": 1},
        "retryable": {"type": "boolean"},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(token in key.casefold() for token in SECRET_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tail(path: Path | None, limit: int = 12000) -> str:
    if path is None or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def exception_from(stderr: str) -> dict[str, str] | None:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        match = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception)):\s*(.*)$", line)
        if match:
            return {"type": match.group(1), "message": match.group(2)}
    return None


def artifact_record(path: Path | None, role: str) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return {
        "role": role,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def available_actions(outcome: str, component: str) -> list[str]:
    if outcome == "success":
        return ["stop"]
    if outcome in {"infrastructure_error", "agent_error"}:
        actions = ["retry_tool", "restart_mcp", "add_test", "stop"]
        if component == "verifier":
            actions[0:0] = ["retry_verifier", "patch_verifier"]
        elif component == "mcp":
            actions.insert(0, "patch_mcp")
        return actions
    return [
        "repair_drawing", "patch_prompt", "patch_skill", "patch_mcp",
        "patch_verifier", "add_test", "stop",
    ]


def build_diagnostic(
    *,
    sample_id: str,
    run_id: str,
    attempt_id: str,
    stage: str,
    component: str,
    outcome: str,
    summary: str,
    retryable: bool,
    return_code: int | None = None,
    timed_out: bool = False,
    verdict: dict[str, Any] | None = None,
    stderr_path: Path | None = None,
    stdout_path: Path | None = None,
    artifacts: Iterable[tuple[Path | None, str]] = (),
    tool_errors: Iterable[Any] = (),
) -> dict[str, Any]:
    stderr = tail(stderr_path)
    stdout = tail(stdout_path)
    verdict = verdict or {}
    completed_checks = []
    failed_checks = []
    for group in ("hard_gates", "dimensions", "rubrics"):
        for item in verdict.get(group, []):
            record = {"group": group, **item}
            if item.get("status") == "pass":
                completed_checks.append(record)
            elif item.get("status") in {"fail", "unverified"}:
                failed_checks.append(record)
    artifact_values = [record for path, role in artifacts if (record := artifact_record(path, role))]
    value = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_id": uuid.uuid4().hex,
        "created_at": utc_now(),
        "sample_id": sample_id,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "outcome": outcome,
        "stage": stage,
        "component": component,
        "retryable": bool(retryable),
        "summary": summary,
        "process": {
            "return_code": return_code,
            "timed_out": bool(timed_out),
            "exception": exception_from(stderr),
            "stderr_tail": stderr,
            "stdout_tail": stdout,
        },
        "verdict": verdict,
        "completed_checks": completed_checks,
        "failed_checks": failed_checks,
        "tool_errors": list(tool_errors),
        "artifacts": artifact_values,
        "available_actions": available_actions(outcome, component),
    }
    return redact(value)


def validate_action(action: dict[str, Any], allowed_files: dict[str, set[str]]) -> dict[str, Any]:
    missing = set(ACTION_SCHEMA["required"]) - set(action)
    extra = set(action) - set(ACTION_SCHEMA["properties"])
    if missing or extra:
        raise ValueError(f"Invalid action keys; missing={sorted(missing)}, extra={sorted(extra)}")
    if action.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported action schema version")
    name = action.get("action")
    if name not in ALLOWED_ACTIONS:
        raise ValueError(f"Unknown action: {name}")
    if action.get("owner") not in OWNERS:
        raise ValueError(f"Unknown owner: {action.get('owner')}")
    component = action.get("component")
    files = action.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise ValueError("Action files must be a string array")
    if len(files) != len(set(files)):
        raise ValueError("Action files must not contain duplicates")
    for relative in files:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Action file escapes the adaptive workspace: {relative}")
    if name in PATCH_COMPONENT:
        expected = PATCH_COMPONENT[name]
        if component != expected or not files:
            raise ValueError(f"{name} requires component={expected} and at least one file")
        unauthorized = set(files) - allowed_files.get(expected, set())
        if unauthorized:
            raise ValueError(f"Unauthorized {expected} files: {sorted(unauthorized)}")
    elif name == "add_test":
        if component != "test" or not files:
            raise ValueError("add_test requires component=test and at least one file")
        if any(not item.startswith("adaptive-tests/") or not item.endswith(".py") for item in files):
            raise ValueError("Adaptive tests must be Python files below adaptive-tests/")
    elif component is not None or files:
        raise ValueError(f"{name} must not declare component files")
    if not isinstance(action.get("rationale"), str) or not action["rationale"].strip():
        raise ValueError("Action rationale is required")
    return action
