from __future__ import annotations

from pathlib import Path

import pytest

from cad_evoloop.agent import (
    ArtifactRef,
    ArtifactRequirement,
    ProjectKernel,
    ProjectStore,
    StageContract,
    WorkResult,
)


def contract() -> StageContract:
    return StageContract(
        contract_id="evidence-to-cad",
        stage="geometry",
        input_requirements=(ArtifactRequirement("design_evidence"),),
        output_requirements=(ArtifactRequirement("cad_model"),),
        verifier_ids=("native-entity", "geometry-valid"),
        description="Create native geometry from design evidence",
    )


class ContractExecutor:
    def __init__(self, store: ProjectStore, output: Path, *, geometry_status: str = "pass") -> None:
        self.store = store
        self.output = output
        self.geometry_status = geometry_status

    def execute(self, context):
        self.store.register_artifact(
            self.output,
            artifact_id=f"candidate-{context.attempt}",
            kind="cad_model",
            producer_work_unit=context.unit["unit_id"],
            parents=("source-drawing",),
        )
        self.store.record_contract_evaluation(
            evaluation_id=f"gate-{context.attempt}",
            contract_id="evidence-to-cad",
            work_unit_id=context.unit["unit_id"],
            execution_id=context.execution_id,
            checks=[
                {"verifier_id": "native-entity", "status": "pass"},
                {"verifier_id": "geometry-valid", "status": self.geometry_status},
            ],
        )
        return WorkResult(
            outcome="succeeded" if self.geometry_status == "pass" else "failed",
            summary="contract evaluated",
        )


def create_contract_project(tmp_path: Path) -> tuple[ProjectStore, Path]:
    store = ProjectStore.create(tmp_path / "projects", "cae-1", "Build a verified CAE model")
    drawing = tmp_path / "drawing.png"
    drawing.write_bytes(b"drawing-evidence")
    candidate = tmp_path / "candidate.step"
    candidate.write_bytes(b"ISO-10303-21; candidate")
    store.register_artifact(
        drawing,
        artifact_id="source-drawing",
        kind="design_evidence",
    )
    store.register_contract(contract())
    store.add_work_unit(
        unit_id="geometry",
        kind="cad",
        phase="geometry",
        title="Create geometry",
        description="Create a native CAD model",
        acceptance_criteria=["The geometry stage contract passes"],
        contract_id="evidence-to-cad",
        input_artifact_ids=["source-drawing"],
    )
    return store, candidate


def test_contract_gate_binds_inputs_outputs_and_verifiers(tmp_path: Path) -> None:
    store, candidate = create_contract_project(tmp_path)

    results = ProjectKernel(store, {"cad": ContractExecutor(store, candidate)}).run()

    assert [item.status for item in results] == ["executed", "completed"]
    state = store.load()
    evaluation = state["contract_evaluations"]["gate-1"]
    assert evaluation["passed"] is True
    assert evaluation["input_artifact_ids"] == ["source-drawing"]
    assert evaluation["output_artifact_ids"] == ["candidate-1"]
    assert state["artifacts"]["candidate-1"]["parents"] == ["source-drawing"]
    assert store.verify()["artifacts_verified"] == 2


def test_contract_gate_prevents_language_only_success(tmp_path: Path) -> None:
    store, _ = create_contract_project(tmp_path)
    state = store.append(
        "work_unit.started",
        {"unit_id": "geometry", "execution_id": "exec-1"},
        actor="kernel",
    )

    with pytest.raises(ValueError, match="passing gate"):
        store.append(
            "work_unit.succeeded",
            {"unit_id": "geometry", "execution_id": "exec-1", "summary": "done"},
            actor="kernel",
        )
    assert state["work_units"]["geometry"]["status"] == "running"


def test_artifact_integrity_is_checked_independently_of_event_chain(tmp_path: Path) -> None:
    store, candidate = create_contract_project(tmp_path)
    ProjectKernel(store, {"cad": ContractExecutor(store, candidate)}).run()
    artifact = store.load()["artifacts"]["candidate-1"]
    (store.project_dir / artifact["uri"]).write_bytes(b"tampered")

    integrity = store.verify()

    assert integrity["ok"] is False
    assert integrity["artifact_errors"] == [
        {"artifact_id": "candidate-1", "error": "size_mismatch"}
    ]


def test_artifact_ref_rejects_invalid_digest() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ArtifactRef(
            artifact_id="bad",
            kind="mesh_model",
            uri="artifacts/bad.msh",
            sha256="bad",
            byte_size=3,
            media_type="application/octet-stream",
        )
