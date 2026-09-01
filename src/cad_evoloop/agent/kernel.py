"""Durable scheduler and execution boundary for long-horizon work units."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
import uuid

from cad_evoloop.agent.state import ready_work_units
from cad_evoloop.agent.store import ProjectStore


WorkOutcome = Literal["succeeded", "retry", "blocked", "failed"]


@dataclass(frozen=True)
class WorkContext:
    project_id: str
    goal: str
    unit: dict[str, Any]
    attempt: int
    execution_id: str
    project_state: dict[str, Any]


@dataclass(frozen=True)
class WorkResult:
    outcome: WorkOutcome
    summary: str
    outputs: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class WorkUnitExecutor(Protocol):
    def execute(self, context: WorkContext) -> WorkResult: ...


@dataclass(frozen=True)
class StepResult:
    status: Literal["executed", "completed", "idle", "paused", "terminal"]
    project_status: str
    unit_id: str | None = None
    execution_id: str | None = None
    outcome: str | None = None


class ProjectKernel:
    def __init__(self, store: ProjectStore, executors: dict[str, WorkUnitExecutor]) -> None:
        self.store = store
        self.executors = executors

    def recover_interrupted(self, *, actor: str = "kernel") -> dict[str, Any]:
        state = self.store.load()
        for unit_id in state["work_order"]:
            unit = state["work_units"][unit_id]
            if unit["status"] != "running":
                continue
            execution_id = unit["active_execution_id"]
            state = self.store.append(
                "work_unit.interrupted",
                {
                    "unit_id": unit_id,
                    "execution_id": execution_id,
                    "error": "Recovered an in-flight work unit after process interruption",
                },
                actor=actor,
                idempotency_key=f"work_unit.interrupted:{execution_id}",
            )
        return state

    def step(self, *, actor: str = "kernel") -> StepResult:
        state = self.store.load()
        if state["status"] == "paused":
            return StepResult(status="paused", project_status="paused")
        if state["status"] in {"completed", "failed", "cancelled"}:
            return StepResult(status="terminal", project_status=state["status"])

        ready = ready_work_units(state)
        if not ready:
            if state["work_units"] and all(
                unit["status"] == "succeeded" for unit in state["work_units"].values()
            ):
                state = self.store.append(
                    "project.completed",
                    {"summary": "All work units satisfied their acceptance workflow"},
                    actor=actor,
                    idempotency_key="project.completed:all-work-units",
                )
                return StepResult(status="completed", project_status=state["status"])
            return StepResult(status="idle", project_status=state["status"])

        unit = ready[0]
        executor = self.executors.get(unit["kind"])
        if executor is None:
            raise LookupError(f"No executor registered for work-unit kind {unit['kind']!r}")
        execution_id = uuid.uuid4().hex
        state = self.store.append(
            "work_unit.started",
            {"unit_id": unit["unit_id"], "execution_id": execution_id},
            actor=actor,
            idempotency_key=f"work_unit.started:{execution_id}",
        )
        running = state["work_units"][unit["unit_id"]]
        context = WorkContext(
            project_id=state["project_id"],
            goal=state["goal"],
            unit=running,
            attempt=running["attempts"],
            execution_id=execution_id,
            project_state=state,
        )
        try:
            result = executor.execute(context)
            if result.outcome not in {"succeeded", "retry", "blocked", "failed"}:
                raise ValueError(f"Unsupported work outcome: {result.outcome!r}")
        except Exception as exc:
            result = WorkResult(
                outcome="retry" if running["attempts"] < running["max_attempts"] else "failed",
                summary="Work-unit executor raised an exception",
                error=repr(exc),
            )

        event_type = {
            "succeeded": "work_unit.succeeded",
            "retry": "work_unit.retry_scheduled",
            "blocked": "work_unit.blocked",
            "failed": "work_unit.failed",
        }[result.outcome]
        state = self.store.append(
            event_type,
            {
                "unit_id": unit["unit_id"],
                "execution_id": execution_id,
                "summary": result.summary,
                "outputs": result.outputs,
                "evidence": result.evidence,
                "error": result.error,
            },
            actor=actor,
            idempotency_key=f"{event_type}:{execution_id}",
        )
        actual_outcome = state["work_units"][unit["unit_id"]]["status"]
        return StepResult(
            status="executed",
            project_status=state["status"],
            unit_id=unit["unit_id"],
            execution_id=execution_id,
            outcome=actual_outcome,
        )

    def run(self, *, max_steps: int | None = None, actor: str = "kernel") -> list[StepResult]:
        if max_steps is not None and max_steps < 1:
            raise ValueError("max_steps must be positive")
        results = []
        while max_steps is None or len(results) < max_steps:
            result = self.step(actor=actor)
            results.append(result)
            if result.status != "executed":
                break
        return results

