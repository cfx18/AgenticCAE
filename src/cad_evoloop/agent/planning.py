"""Hierarchical, versioned engineering plans compiled into the GoalGraph."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from cad_evoloop.agent.contracts import ArtifactRequirement, StageContract
from cad_evoloop.agent.store import ProjectStore


CAE_PHASES = (
    "requirements",
    "geometry",
    "analysis_model",
    "mesh",
    "solve",
    "postprocess",
    "assessment",
    "optimization",
)


@dataclass(frozen=True)
class WorkUnitSpec:
    unit_id: str
    kind: str
    phase: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    contract_id: str | None = None
    input_artifact_ids: tuple[str, ...] = ()
    max_attempts: int = 3
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineeringPlan:
    plan_id: str
    objective: str
    work_units: tuple[WorkUnitSpec, ...]
    contracts: tuple[StageContract, ...] = ()
    parent_plan_id: str | None = None
    rationale: str = ""

    def topological_work_units(self) -> list[WorkUnitSpec]:
        if not self.plan_id.strip() or not self.objective.strip():
            raise ValueError("Plan identity and objective are required")
        by_id = {unit.unit_id: unit for unit in self.work_units}
        if len(by_id) != len(self.work_units):
            raise ValueError("Engineering plan work-unit identifiers must be unique")
        unknown = {
            dependency
            for unit in self.work_units
            for dependency in unit.dependencies
            if dependency not in by_id
        }
        if unknown:
            raise ValueError(f"Engineering plan has unknown dependencies: {sorted(unknown)}")
        remaining = {unit.unit_id: set(unit.dependencies) for unit in self.work_units}
        ordered = []
        while remaining:
            ready = [unit.unit_id for unit in self.work_units if unit.unit_id in remaining and not remaining[unit.unit_id]]
            if not ready:
                raise ValueError("Engineering plan dependency graph contains a cycle")
            for unit_id in ready:
                ordered.append(by_id[unit_id])
                del remaining[unit_id]
                for dependencies in remaining.values():
                    dependencies.discard(unit_id)
        return ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "parent_plan_id": self.parent_plan_id,
            "objective": self.objective,
            "rationale": self.rationale,
            "contract_ids": [contract.contract_id for contract in self.contracts],
            "work_units": [
                {
                    **asdict(unit),
                    "acceptance_criteria": list(unit.acceptance_criteria),
                    "dependencies": list(unit.dependencies),
                    "input_artifact_ids": list(unit.input_artifact_ids),
                }
                for unit in self.work_units
            ],
        }


def apply_plan(store: ProjectStore, plan: EngineeringPlan, *, actor: str = "planner") -> dict[str, Any]:
    ordered = plan.topological_work_units()
    store.register_plan(plan, actor=actor)
    for contract in plan.contracts:
        store.register_contract(contract, actor=actor)
    state = store.load()
    for unit in ordered:
        state = store.add_work_unit(
            unit_id=unit.unit_id,
            kind=unit.kind,
            phase=unit.phase,
            title=unit.title,
            description=unit.description,
            acceptance_criteria=unit.acceptance_criteria,
            dependencies=unit.dependencies,
            contract_id=unit.contract_id,
            input_artifact_ids=unit.input_artifact_ids,
            max_attempts=unit.max_attempts,
            parameters=unit.parameters,
            plan_id=plan.plan_id,
            actor=actor,
        )
    return state


def standard_cae_plan(*, evidence_artifact_id: str, plan_id: str = "cae-plan-v1") -> EngineeringPlan:
    definitions = [
        ("requirements", ("design_evidence",), "requirement_model", ("requirements-schema", "units-valid")),
        ("geometry", ("requirement_model",), "cad_model", ("native-geometry", "topology-valid")),
        ("analysis_model", ("requirement_model", "cad_model"), "analysis_model", ("physics-complete", "units-valid")),
        ("mesh", ("analysis_model",), "mesh_model", ("mesh-valid", "mesh-quality")),
        ("solve", ("analysis_model", "mesh_model"), "result_field", ("solver-converged", "equilibrium-valid")),
        ("postprocess", ("result_field",), "postprocess_result", ("result-readable", "quantities-complete")),
        ("assessment", ("requirement_model", "postprocess_result"), "engineering_report", ("requirements-traced", "conclusions-supported")),
    ]
    contracts = tuple(
        StageContract(
            contract_id=f"{stage}-contract-v1",
            stage=stage,
            input_requirements=tuple(ArtifactRequirement(kind) for kind in inputs),
            output_requirements=(ArtifactRequirement(output),),
            verifier_ids=verifiers,
        )
        for stage, inputs, output, verifiers in definitions
    )
    units = []
    producers: dict[str, str] = {}
    for stage, inputs, output, _ in definitions:
        unit_id = f"phase-{stage.replace('_', '-')}"
        dependencies = tuple(
            dict.fromkeys(producers[kind] for kind in inputs if kind in producers)
        )
        units.append(WorkUnitSpec(
            unit_id=unit_id,
            kind=stage,
            phase=stage,
            title=stage.replace("_", " ").title(),
            description=f"Produce and verify the {stage.replace('_', ' ')} stage artifact",
            acceptance_criteria=[f"{stage.replace('_', ' ')} contract passes"],
            dependencies=dependencies,
            contract_id=f"{stage}-contract-v1",
            input_artifact_ids=((evidence_artifact_id,) if stage == "requirements" else ()),
        ))
        producers[output] = unit_id
    return EngineeringPlan(
        plan_id=plan_id,
        objective="Build a traceable CAD-to-CAE analysis and engineering assessment",
        work_units=tuple(units),
        contracts=contracts,
        rationale="Canonical seven-stage CAE workflow",
    )
