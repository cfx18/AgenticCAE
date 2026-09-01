"""Pure project-state reducer for the long-horizon agent kernel."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


PROJECT_STATUSES = {"active", "paused", "completed", "failed", "cancelled"}
WORK_STATUSES = {"pending", "running", "blocked", "succeeded", "failed", "cancelled"}
TERMINAL_PROJECT_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_WORK_STATUSES = {"succeeded", "failed", "cancelled"}


def empty_state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "goal": None,
        "status": None,
        "metadata": {},
        "work_units": {},
        "work_order": [],
        "last_sequence": 0,
        "last_event_hash": None,
        "created_at": None,
        "updated_at": None,
        "completion_summary": None,
    }


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _work_unit(state: dict[str, Any], unit_id: Any) -> dict[str, Any]:
    unit_id = _required_text(unit_id, "unit_id")
    try:
        return state["work_units"][unit_id]
    except KeyError as exc:
        raise ValueError(f"Unknown work unit: {unit_id}") from exc


def _require_project_active(state: dict[str, Any]) -> None:
    if state["status"] != "active":
        raise ValueError(f"Project must be active, found {state['status']!r}")


def _validate_dependencies(state: dict[str, Any], unit_id: str, dependencies: Any) -> list[str]:
    if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
        raise ValueError("dependencies must be an array of work-unit identifiers")
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("dependencies must not contain duplicates")
    if unit_id in dependencies:
        raise ValueError("A work unit cannot depend on itself")
    unknown = [item for item in dependencies if item not in state["work_units"]]
    if unknown:
        raise ValueError(f"Work-unit dependencies must already exist: {unknown}")
    return dependencies


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    payload = event["payload"]
    event_type = event["event_type"]

    if event_type == "project.created":
        if next_state["status"] is not None:
            raise ValueError("Project has already been created")
        next_state["goal"] = _required_text(payload.get("goal"), "goal")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("project metadata must be an object")
        next_state["metadata"] = metadata
        next_state["status"] = "active"
        next_state["created_at"] = event["occurred_at"]

    elif event_type == "project.paused":
        _require_project_active(next_state)
        next_state["status"] = "paused"

    elif event_type == "project.resumed":
        if next_state["status"] != "paused":
            raise ValueError("Only a paused project can resume")
        next_state["status"] = "active"

    elif event_type in {"project.completed", "project.failed", "project.cancelled"}:
        if next_state["status"] in TERMINAL_PROJECT_STATUSES:
            raise ValueError("Project is already terminal")
        target = event_type.split(".", 1)[1]
        if target == "completed" and any(
            unit["status"] != "succeeded" for unit in next_state["work_units"].values()
        ):
            raise ValueError("Project cannot complete before every work unit succeeds")
        next_state["status"] = target
        next_state["completion_summary"] = payload.get("summary")

    elif event_type == "work_unit.added":
        _require_project_active(next_state)
        unit_id = _required_text(payload.get("unit_id"), "unit_id")
        if unit_id in next_state["work_units"]:
            raise ValueError(f"Duplicate work unit: {unit_id}")
        dependencies = _validate_dependencies(next_state, unit_id, payload.get("dependencies", []))
        acceptance = payload.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance or any(
            not isinstance(item, str) or not item.strip() for item in acceptance
        ):
            raise ValueError("acceptance_criteria must contain at least one non-empty string")
        max_attempts = payload.get("max_attempts", 3)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        next_state["work_units"][unit_id] = {
            "unit_id": unit_id,
            "kind": _required_text(payload.get("kind", "generic"), "kind"),
            "title": _required_text(payload.get("title"), "title"),
            "description": _required_text(payload.get("description"), "description"),
            "dependencies": dependencies,
            "acceptance_criteria": [item.strip() for item in acceptance],
            "max_attempts": max_attempts,
            "status": "pending",
            "attempts": 0,
            "active_execution_id": None,
            "last_error": None,
            "summary": None,
            "outputs": [],
            "evidence": [],
            "added_at": event["occurred_at"],
            "updated_at": event["occurred_at"],
        }
        next_state["work_order"].append(unit_id)

    elif event_type == "work_unit.started":
        _require_project_active(next_state)
        unit = _work_unit(next_state, payload.get("unit_id"))
        if unit["status"] != "pending":
            raise ValueError(f"Work unit {unit['unit_id']} is not pending")
        unsatisfied = [
            item for item in unit["dependencies"]
            if next_state["work_units"][item]["status"] != "succeeded"
        ]
        if unsatisfied:
            raise ValueError(f"Work unit dependencies are not satisfied: {unsatisfied}")
        if unit["attempts"] >= unit["max_attempts"]:
            raise ValueError(f"Work unit {unit['unit_id']} exhausted its attempts")
        execution_id = _required_text(payload.get("execution_id"), "execution_id")
        unit["status"] = "running"
        unit["attempts"] += 1
        unit["active_execution_id"] = execution_id
        unit["updated_at"] = event["occurred_at"]

    elif event_type in {
        "work_unit.succeeded", "work_unit.retry_scheduled", "work_unit.blocked",
        "work_unit.failed", "work_unit.cancelled", "work_unit.interrupted",
    }:
        unit = _work_unit(next_state, payload.get("unit_id"))
        execution_id = payload.get("execution_id")
        if unit["status"] != "running":
            raise ValueError(f"Work unit {unit['unit_id']} is not running")
        if execution_id != unit["active_execution_id"]:
            raise ValueError(f"Execution receipt does not match work unit {unit['unit_id']}")
        outcome = event_type.split(".", 1)[1]
        if outcome in {"retry_scheduled", "interrupted"}:
            if unit["attempts"] >= unit["max_attempts"]:
                unit["status"] = "failed"
            else:
                unit["status"] = "pending"
        else:
            unit["status"] = outcome
        unit["active_execution_id"] = None
        unit["last_error"] = payload.get("error")
        unit["summary"] = payload.get("summary") or unit["summary"]
        outputs = payload.get("outputs", [])
        evidence = payload.get("evidence", [])
        if not isinstance(outputs, list) or not isinstance(evidence, list):
            raise ValueError("Work-unit outputs and evidence must be arrays")
        if outputs:
            unit["outputs"] = outputs
        if evidence:
            unit["evidence"] = evidence
        unit["updated_at"] = event["occurred_at"]

    elif event_type == "work_unit.reopened":
        _require_project_active(next_state)
        unit = _work_unit(next_state, payload.get("unit_id"))
        if unit["status"] not in {"blocked", "failed", "cancelled"}:
            raise ValueError(f"Work unit {unit['unit_id']} cannot be reopened from {unit['status']}")
        if unit["attempts"] >= unit["max_attempts"]:
            additional_attempts = payload.get("additional_attempts", 0)
            if (
                isinstance(additional_attempts, bool)
                or not isinstance(additional_attempts, int)
                or additional_attempts < 1
            ):
                raise ValueError("Reopening an exhausted unit requires additional_attempts")
            unit["max_attempts"] += additional_attempts
        unit["status"] = "pending"
        unit["last_error"] = None
        unit["updated_at"] = event["occurred_at"]

    else:
        raise ValueError(f"Unsupported project event type: {event_type}")

    if next_state["status"] not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status: {next_state['status']!r}")
    if any(unit["status"] not in WORK_STATUSES for unit in next_state["work_units"].values()):
        raise ValueError("Invalid work-unit status")
    next_state["last_sequence"] = event["sequence"]
    next_state["last_event_hash"] = event["event_hash"]
    next_state["updated_at"] = event["occurred_at"]
    return next_state


def replay(project_id: str, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    state = empty_state(project_id)
    for event in events:
        state = apply_event(state, event)
    return state


def ready_work_units(state: dict[str, Any]) -> list[dict[str, Any]]:
    if state["status"] != "active":
        return []
    return [
        state["work_units"][unit_id]
        for unit_id in state["work_order"]
        if state["work_units"][unit_id]["status"] == "pending"
        and all(
            state["work_units"][dependency]["status"] == "succeeded"
            for dependency in state["work_units"][unit_id]["dependencies"]
        )
    ]

