"""Bounded, structured context views derived from durable project state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ContextView:
    project: dict[str, Any]
    active_plan: dict[str, Any] | None
    focus: dict[str, Any] | None
    completed: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    unresolved_operations: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "active_plan": self.active_plan,
            "focus": self.focus,
            "completed": self.completed,
            "blocked": self.blocked,
            "artifacts": self.artifacts,
            "unresolved_operations": self.unresolved_operations,
            "recent_events": self.recent_events,
        }


def _unit_view(unit: dict[str, Any], *, include_evidence: bool) -> dict[str, Any]:
    value = {
        "unit_id": unit["unit_id"],
        "kind": unit["kind"],
        "title": unit["title"],
        "description": unit["description"],
        "phase": unit["phase"],
        "plan_id": unit["plan_id"],
        "contract_id": unit["contract_id"],
        "status": unit["status"],
        "dependencies": list(unit["dependencies"]),
        "acceptance_criteria": list(unit["acceptance_criteria"]),
        "attempts": unit["attempts"],
        "max_attempts": unit["max_attempts"],
        "summary": unit["summary"],
        "outputs": list(unit["outputs"]),
        "input_artifact_ids": list(unit["input_artifact_ids"]),
        "artifact_ids": list(unit["artifact_ids"]),
        "latest_contract_evaluation_id": unit["latest_contract_evaluation_id"],
        "parameters": unit["parameters"],
        "last_error": unit["last_error"],
    }
    if include_evidence:
        value["evidence"] = list(unit["evidence"])
    return value


def build_context_view(
    state: dict[str, Any],
    events: Iterable[dict[str, Any]],
    *,
    focus_unit_id: str | None = None,
    recent_event_limit: int = 8,
) -> ContextView:
    if recent_event_limit < 0:
        raise ValueError("recent_event_limit must not be negative")
    if focus_unit_id is not None and focus_unit_id not in state["work_units"]:
        raise ValueError(f"Unknown focus work unit: {focus_unit_id}")

    event_list = list(events)
    recent = event_list[-recent_event_limit:] if recent_event_limit else []
    recent_views = [
        {
            "sequence": event["sequence"],
            "event_type": event["event_type"],
            "occurred_at": event["occurred_at"],
            "actor": event["actor"],
            "payload": event["payload"],
        }
        for event in recent
    ]
    completed = [
        _unit_view(state["work_units"][unit_id], include_evidence=True)
        for unit_id in state["work_order"]
        if state["work_units"][unit_id]["status"] == "succeeded"
    ]
    blocked = [
        _unit_view(state["work_units"][unit_id], include_evidence=True)
        for unit_id in state["work_order"]
        if state["work_units"][unit_id]["status"] in {"blocked", "failed"}
    ]
    focus = (
        _unit_view(state["work_units"][focus_unit_id], include_evidence=True)
        if focus_unit_id is not None
        else None
    )
    artifacts = [state["artifacts"][artifact_id] for artifact_id in state["artifact_order"]]
    unresolved_operations = [
        state["operations"][operation_id]
        for operation_id in state["operation_order"]
        if state["operations"][operation_id]["status"] in {"running", "uncertain", "retryable"}
    ]
    active_plan = (
        state["plans"][state["plan_order"][-1]] if state["plan_order"] else None
    )
    return ContextView(
        project={
            "project_id": state["project_id"],
            "goal": state["goal"],
            "status": state["status"],
            "metadata": state["metadata"],
            "last_sequence": state["last_sequence"],
        },
        active_plan=active_plan,
        focus=focus,
        completed=completed,
        blocked=blocked,
        artifacts=artifacts,
        unresolved_operations=unresolved_operations,
        recent_events=recent_views,
    )
