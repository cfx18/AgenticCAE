from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.agent import ProjectKernel, ProjectStore, WorkResult, build_context_view


class RecordingExecutor:
    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = None if outcomes is None else list(outcomes)
        self.calls = []

    def execute(self, context):
        self.calls.append(context)
        outcome = "succeeded" if self.outcomes is None else self.outcomes.pop(0)
        return WorkResult(
            outcome=outcome,
            summary=f"{context.unit['unit_id']} {outcome}",
            outputs=[{"path": f"artifacts/{context.unit['unit_id']}.json"}],
            evidence=[{"check": "acceptance", "passed": outcome == "succeeded"}],
            error=None if outcome == "succeeded" else "recoverable failure",
        )


def create_project(tmp_path: Path) -> ProjectStore:
    return ProjectStore.create(
        tmp_path / "projects",
        "project-1",
        "Build and validate a CAD assembly",
        metadata={"owner": "test"},
    )


def test_project_kernel_executes_dependency_graph_and_replays_state(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    store.add_work_unit(
        unit_id="part-a", kind="cad", title="Model part A", description="Create native geometry",
        acceptance_criteria=["Native solid exists"],
    )
    store.add_work_unit(
        unit_id="assembly", kind="cad", title="Assemble parts", description="Create the assembly",
        dependencies=["part-a"], acceptance_criteria=["No interference"],
    )
    executor = RecordingExecutor()
    kernel = ProjectKernel(store, {"cad": executor})

    results = kernel.run()

    assert [result.status for result in results] == ["executed", "executed", "completed"]
    assert [call.unit["unit_id"] for call in executor.calls] == ["part-a", "assembly"]
    state = ProjectStore(tmp_path / "projects", "project-1").load()
    assert state["status"] == "completed"
    assert state["work_units"]["assembly"]["evidence"][0]["passed"] is True
    assert store.verify()["ok"] is True


def test_retry_preserves_attempt_identity_and_stops_at_success(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    store.add_work_unit(
        unit_id="part", kind="cad", title="Model part", description="Create native geometry",
        acceptance_criteria=["Geometry verifier passes"], max_attempts=3,
    )
    executor = RecordingExecutor(["retry", "succeeded"])
    kernel = ProjectKernel(store, {"cad": executor})

    results = kernel.run()

    assert [result.outcome for result in results[:2]] == ["pending", "succeeded"]
    state = store.load()
    assert state["status"] == "completed"
    assert state["work_units"]["part"]["attempts"] == 2
    assert executor.calls[0].execution_id != executor.calls[1].execution_id


def test_executor_exception_is_recorded_and_retried(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    store.add_work_unit(
        unit_id="part", kind="cad", title="Model part", description="Create native geometry",
        acceptance_criteria=["Geometry verifier passes"], max_attempts=2,
    )
    executor = RecordingExecutor([])
    kernel = ProjectKernel(store, {"cad": executor})

    first = kernel.step()

    assert first.outcome == "pending"
    unit = store.load()["work_units"]["part"]
    assert unit["last_error"].startswith("IndexError")
    assert unit["attempts"] == 1


def test_kernel_recovers_inflight_work_after_process_restart(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    store.add_work_unit(
        unit_id="part", kind="cad", title="Model part", description="Create native geometry",
        acceptance_criteria=["Artifact exists"], max_attempts=2,
    )
    store.append(
        "work_unit.started",
        {"unit_id": "part", "execution_id": "orphaned-execution"},
        actor="kernel",
    )

    kernel = ProjectKernel(store, {"cad": RecordingExecutor()})
    recovered = kernel.recover_interrupted()

    assert recovered["work_units"]["part"]["status"] == "pending"
    assert recovered["work_units"]["part"]["attempts"] == 1
    assert kernel.run()[-1].status == "completed"
    assert store.load()["work_units"]["part"]["attempts"] == 2


def test_event_chain_detects_tampering_and_snapshot_is_rebuilt(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    original = store.load()
    store.state_path.write_text('{"stale":true}\n', encoding="utf-8")

    assert store.load() == original

    store.state_path.write_text("{broken", encoding="utf-8")
    assert store.load() == original

    lines = store.events_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["goal"] = "tampered"
    store.events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        store.load()


def test_work_unit_requires_existing_dependencies_and_acceptance_criteria(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    with pytest.raises(ValueError, match="dependencies must already exist"):
        store.add_work_unit(
            unit_id="assembly", kind="cad", title="Assembly", description="Assemble",
            dependencies=["missing"], acceptance_criteria=["Valid"],
        )
    with pytest.raises(ValueError, match="acceptance_criteria"):
        store.add_work_unit(
            unit_id="empty", kind="cad", title="Empty", description="No criteria",
            acceptance_criteria=[],
        )


def test_idempotency_key_does_not_duplicate_project_events(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    payload = {
        "unit_id": "part", "kind": "cad", "title": "Part", "description": "Model it",
        "dependencies": [], "acceptance_criteria": ["Valid"], "max_attempts": 1,
    }
    store.append("work_unit.added", payload, actor="planner", idempotency_key="add-part")
    store.append("work_unit.added", payload, actor="planner", idempotency_key="add-part")

    assert len(store.events()) == 2

    conflicting = dict(payload, title="Different part")
    with pytest.raises(ValueError, match="reused with different content"):
        store.append("work_unit.added", conflicting, actor="planner", idempotency_key="add-part")


def test_context_view_is_bounded_and_keeps_verified_artifacts(tmp_path: Path) -> None:
    store = create_project(tmp_path)
    store.add_work_unit(
        unit_id="part", kind="cad", title="Part", description="Model the part",
        acceptance_criteria=["Solid is valid"],
    )
    ProjectKernel(store, {"cad": RecordingExecutor()}).step()

    view = build_context_view(
        store.load(), store.events(), focus_unit_id="part", recent_event_limit=2,
    ).to_dict()

    assert view["focus"]["unit_id"] == "part"
    assert view["completed"][0]["outputs"] == [{"path": "artifacts/part.json"}]
    assert view["completed"][0]["evidence"][0]["passed"] is True
    assert len(view["recent_events"]) == 2
    assert "event_hash" not in view["recent_events"][0]
