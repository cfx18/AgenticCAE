from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cad_evoloop.agent import (
    EngineeringPlan,
    ProjectStore,
    WorkUnitSpec,
    apply_plan,
    standard_cae_plan,
    build_context_view,
)


def project_with_evidence(tmp_path: Path) -> ProjectStore:
    store = ProjectStore.create(tmp_path / "projects", "plan-1", "Analyze a component")
    evidence = tmp_path / "brief.txt"
    evidence.write_text("cantilever bracket", encoding="utf-8")
    store.register_artifact(evidence, artifact_id="brief", kind="design_evidence")
    return store


def test_standard_cae_plan_compiles_to_seven_typed_phases(tmp_path: Path) -> None:
    store = project_with_evidence(tmp_path)

    state = apply_plan(store, standard_cae_plan(evidence_artifact_id="brief"))

    assert [state["work_units"][unit_id]["phase"] for unit_id in state["work_order"]] == [
        "requirements", "geometry", "analysis_model", "mesh", "solve",
        "postprocess", "assessment",
    ]
    assert len(state["contracts"]) == 7
    assert state["work_units"]["phase-requirements"]["input_artifact_ids"] == ["brief"]
    assert state["work_units"]["phase-analysis-model"]["dependencies"] == [
        "phase-requirements", "phase-geometry",
    ]
    assert state["work_units"]["phase-solve"]["dependencies"] == [
        "phase-analysis-model", "phase-mesh",
    ]
    assert state["work_units"]["phase-assessment"]["dependencies"] == [
        "phase-requirements", "phase-postprocess",
    ]
    assert state["plans"]["cae-plan-v1"]["rationale"] == "Canonical seven-stage CAE workflow"
    context = build_context_view(state, store.events(), focus_unit_id="phase-requirements")
    assert context.active_plan["plan_id"] == "cae-plan-v1"
    assert context.artifacts[0]["artifact_id"] == "brief"
    assert context.focus["contract_id"] == "requirements-contract-v1"


def test_plan_is_topologically_sorted_before_it_is_applied(tmp_path: Path) -> None:
    store = project_with_evidence(tmp_path)
    first = WorkUnitSpec(
        unit_id="first", kind="generic", phase="requirements", title="First",
        description="First", acceptance_criteria=("done",),
    )
    second = WorkUnitSpec(
        unit_id="second", kind="generic", phase="geometry", title="Second",
        description="Second", acceptance_criteria=("done",), dependencies=("first",),
    )
    plan = EngineeringPlan("unordered", "Test ordering", (second, first))

    state = apply_plan(store, plan)

    assert state["work_order"] == ["first", "second"]


def test_plan_cycle_is_rejected_without_writing_events(tmp_path: Path) -> None:
    store = project_with_evidence(tmp_path)
    a = WorkUnitSpec(
        unit_id="a", kind="generic", phase="geometry", title="A", description="A",
        acceptance_criteria=("done",), dependencies=("b",),
    )
    b = replace(a, unit_id="b", title="B", dependencies=("a",))
    before = len(store.events())

    with pytest.raises(ValueError, match="cycle"):
        apply_plan(store, EngineeringPlan("cyclic", "Invalid", (a, b)))

    assert len(store.events()) == before
