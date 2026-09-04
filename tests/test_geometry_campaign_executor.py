from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.agent import ArtifactRequirement, ProjectKernel, ProjectStore, StageContract
from cad_evoloop.agent.executors import GeometryCampaignExecutor, GeometryCampaignExecutorConfig


def test_geometry_campaign_is_a_contract_bound_work_unit(tmp_path: Path) -> None:
    data = tmp_path / "data"
    sample_dir = data / "sample"
    sample_dir.mkdir(parents=True)
    (sample_dir / "input.png").write_bytes(b"input")
    (sample_dir / "truth.step").write_bytes(b"truth")
    manifest = data / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": [{
            "sample_id": "sample:1",
            "dataset": "test",
            "task": "image-to-cad",
            "input_images": ["sample/input.png"],
            "ground_truth_step": "sample/truth.step",
        }],
    }), encoding="utf-8")
    store = ProjectStore.create(tmp_path / "projects", "geometry-project", "Model one sample")
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    store.register_artifact(evidence, artifact_id="input-evidence", kind="design_evidence")
    store.register_contract(StageContract(
        contract_id="geometry-gate",
        stage="geometry",
        input_requirements=(ArtifactRequirement("design_evidence"),),
        output_requirements=(ArtifactRequirement("cad_model"),),
        verifier_ids=("native-geometry", "strict-geometry"),
    ))
    store.add_work_unit(
        unit_id="geometry-sample-1",
        kind="geometry_campaign",
        phase="geometry",
        title="Geometry sample 1",
        description="Run the recorded geometry loop",
        acceptance_criteria=["Strict geometry gate passes"],
        contract_id="geometry-gate",
        input_artifact_ids=["input-evidence"],
        parameters={"sample_id": "sample:1"},
    )

    captured = {}

    def runner(**kwargs):
        captured.update(kwargs)
        job = tmp_path / "campaign-job"
        job.mkdir()
        (job / "candidate.dwg").write_bytes(b"dwg")
        (job / "candidate.stl").write_bytes(b"stl")
        (job / "geometry-verdict.json").write_text('{"passed":true}', encoding="utf-8")
        result = {
            "job_dir": str(job), "passed": True, "score": 100.0,
            "stop_reason": "strict_pass", "selected_attempt_id": "a001", "attempts": [{}],
        }
        (job / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    executor = GeometryCampaignExecutor(
        store,
        GeometryCampaignExecutorConfig(
            manifest_path=manifest, campaign="test-campaign", executable="codex-test",
        ),
        runner=runner,
    )

    results = ProjectKernel(store, {"geometry_campaign": executor}).run()

    assert results[-1].status == "completed"
    assert captured["reconstruction_mode"] == "baseline"
    state = store.load()
    assert state["work_units"]["geometry-sample-1"]["status"] == "succeeded"
    gate = state["contract_evaluations"]["geometry-sample-1-1-gate"]
    assert gate["passed"] is True
    assert {state["artifacts"][item]["kind"] for item in gate["output_artifact_ids"]} >= {
        "cad_model", "surface_mesh", "verifier_report", "trajectory_result",
    }
