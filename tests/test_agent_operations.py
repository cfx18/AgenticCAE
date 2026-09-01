from __future__ import annotations

from pathlib import Path

import pytest

from cad_evoloop.agent import (
    OperationBroker,
    OperationNeedsReconciliation,
    ProjectStore,
    ReconciliationResult,
)


def running_project(tmp_path: Path) -> tuple[ProjectStore, str]:
    store = ProjectStore.create(tmp_path / "projects", "ops-1", "Run a solver")
    store.add_work_unit(
        unit_id="solve",
        kind="solver",
        title="Solve",
        description="Run the external solver",
        acceptance_criteria=["Solver terminates normally"],
    )
    execution_id = "execution-1"
    store.append(
        "work_unit.started",
        {"unit_id": "solve", "execution_id": execution_id},
        actor="kernel",
    )
    return store, execution_id


def test_completed_operation_is_returned_without_repeating_side_effect(tmp_path: Path) -> None:
    store, execution_id = running_project(tmp_path)
    broker = OperationBroker(store)
    calls = []

    def action():
        calls.append("called")
        return {"return_code": 0}

    first = broker.execute(
        operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
        name="calculix.run", arguments={"deck": "case.inp"}, action=action,
    )
    second = broker.execute(
        operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
        name="calculix.run", arguments={"deck": "case.inp"}, action=action,
    )

    assert first == second == {"return_code": 0}
    assert calls == ["called"]
    assert store.load()["operations"]["solver-run-1"]["status"] == "completed"


def test_interrupted_operation_requires_explicit_reconciliation(tmp_path: Path) -> None:
    store, execution_id = running_project(tmp_path)
    store.append(
        "operation.started",
        {
            "operation_id": "solver-run-1",
            "work_unit_id": "solve",
            "execution_id": execution_id,
            "name": "calculix.run",
            "arguments": {"deck": "case.inp"},
            "request_digest": OperationBroker.request_digest(
                "calculix.run", {"deck": "case.inp"},
            ),
        },
        actor="tool-broker",
    )

    with pytest.raises(OperationNeedsReconciliation):
        OperationBroker(store).execute(
            operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
            name="calculix.run", arguments={"deck": "case.inp"}, action=lambda: {},
        )
    assert store.load()["operations"]["solver-run-1"]["status"] == "uncertain"


def test_reconciler_can_adopt_effect_observed_in_external_system(tmp_path: Path) -> None:
    store, execution_id = running_project(tmp_path)
    broker = OperationBroker(store)
    store.append(
        "operation.started",
        {
            "operation_id": "solver-run-1", "work_unit_id": "solve",
            "execution_id": execution_id, "name": "calculix.run",
            "arguments": {"deck": "case.inp"},
            "request_digest": broker.request_digest("calculix.run", {"deck": "case.inp"}),
        },
        actor="tool-broker",
    )
    calls = []

    result = broker.execute(
        operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
        name="calculix.run", arguments={"deck": "case.inp"},
        action=lambda: calls.append("repeated") or {},
        reconcile=lambda record: ReconciliationResult(
            disposition="adopt",
            summary="Result database exists and matches the request digest",
            result={"return_code": 0, "adopted": True},
        ),
    )

    assert result == {"return_code": 0, "adopted": True}
    assert calls == []


def test_operation_identifier_cannot_change_request(tmp_path: Path) -> None:
    store, execution_id = running_project(tmp_path)
    broker = OperationBroker(store)
    broker.execute(
        operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
        name="calculix.run", arguments={"deck": "a.inp"}, action=lambda: {},
    )
    with pytest.raises(ValueError, match="different request"):
        broker.execute(
            operation_id="solver-run-1", work_unit_id="solve", execution_id=execution_id,
            name="calculix.run", arguments={"deck": "b.inp"}, action=lambda: {},
        )
