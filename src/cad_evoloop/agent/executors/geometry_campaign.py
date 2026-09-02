"""Compatibility executor that runs one recorded geometry campaign job."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Any, Callable

from cad_evoloop.agent.kernel import WorkContext, WorkResult
from cad_evoloop.agent.store import ProjectStore
from cad_evoloop.evaluation.geometry_campaign import load_geometry_manifest, run_geometry_job


@dataclass(frozen=True)
class GeometryCampaignExecutorConfig:
    manifest_path: Path
    campaign: str
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "medium"
    executable: str | None = None
    timeout_seconds: int = 900
    max_iterations: int = 12
    stagnation_limit: int = 2
    job_time_budget_seconds: int = 3600
    score_samples: int = 20000
    voxel_resolution: int = 64
    split_path: Path | None = None


class GeometryCampaignExecutor:
    def __init__(
        self,
        store: ProjectStore,
        config: GeometryCampaignExecutorConfig,
        *,
        runner: Callable[..., dict[str, Any]] = run_geometry_job,
    ) -> None:
        self.store = store
        self.config = config
        self.runner = runner
        self.manifest_path, manifest = load_geometry_manifest(config.manifest_path)
        self.samples = {sample["sample_id"]: sample for sample in manifest["samples"]}
        self.executable = config.executable or shutil.which("codex")
        if not self.executable:
            raise FileNotFoundError("codex executable was not found")

    def execute(self, context: WorkContext) -> WorkResult:
        sample_id = context.unit["parameters"].get("sample_id")
        if sample_id not in self.samples:
            return WorkResult(
                outcome="failed",
                summary="Geometry work unit references an unknown sample",
                error=f"Unknown geometry sample: {sample_id!r}",
            )
        feedback_candidates = [
            artifact for artifact in context.project_state["artifacts"].values()
            if artifact["kind"] == "human_feedback" and (
                artifact["artifact_id"] in context.unit["input_artifact_ids"]
                or artifact.get("producer_work_unit") in context.unit["dependencies"]
            )
        ]
        feedback_artifact = next((
            artifact for artifact in feedback_candidates
            if artifact.get("metadata", {}).get("resolved")
        ), feedback_candidates[0] if feedback_candidates else None)
        human_feedback = (
            self.store.project_dir / feedback_artifact["uri"]
            if feedback_artifact else None
        )
        result = self.runner(
            manifest_path=self.manifest_path,
            sample=self.samples[sample_id],
            campaign=self.config.campaign,
            model=self.config.model,
            effort=self.config.reasoning_effort,
            executable=self.executable,
            timeout=self.config.timeout_seconds,
            max_iterations=self.config.max_iterations,
            stagnation_limit=self.config.stagnation_limit,
            job_time_budget=self.config.job_time_budget_seconds,
            score_samples=self.config.score_samples,
            voxel_resolution=self.config.voxel_resolution,
            split_path=self.config.split_path,
            human_feedback=human_feedback,
        )
        job_dir = Path(result["job_dir"])
        parent_ids = tuple(dict.fromkeys([
            *context.unit["input_artifact_ids"],
            *([feedback_artifact["artifact_id"]] if feedback_artifact else []),
        ]))
        registered = []
        files = [
            (job_dir / "candidate.dwg", "cad_model", "candidate"),
            (job_dir / "candidate.stl", "surface_mesh", "candidate-mesh"),
            (job_dir / "candidate-topology.json", "cad_topology", "candidate-topology"),
            (job_dir / "face-query.json", "cad_face_query", "candidate-face-query"),
            (job_dir / "geometry-verdict.json", "verifier_report", "verdict"),
            (job_dir / "result.json", "trajectory_result", "result"),
        ]
        for path, kind, label in files:
            if not path.is_file():
                continue
            artifact_id = f"{context.unit['unit_id']}-{context.attempt}-{label}"
            self.store.register_artifact(
                path,
                artifact_id=artifact_id,
                kind=kind,
                producer_work_unit=context.unit["unit_id"],
                parents=parent_ids,
                metadata={
                    "sample_id": sample_id,
                    "campaign": self.config.campaign,
                    "model": self.config.model,
                    "selected_attempt_id": result.get("selected_attempt_id"),
                },
            )
            registered.append(artifact_id)

        if context.unit["contract_id"] is not None:
            state = self.store.load()
            contract = state["contracts"][context.unit["contract_id"]]
            has_candidate = any(
                state["artifacts"][artifact_id]["kind"] == "cad_model"
                for artifact_id in registered
            )
            checks = []
            for verifier_id in contract["verifier_ids"]:
                status = "pass" if bool(result.get("passed")) else "fail"
                if "native" in verifier_id or "artifact" in verifier_id:
                    status = "pass" if has_candidate else "fail"
                checks.append({
                    "verifier_id": verifier_id,
                    "status": status,
                    "score": result.get("score"),
                    "stop_reason": result.get("stop_reason"),
                })
            self.store.record_contract_evaluation(
                evaluation_id=f"{context.unit['unit_id']}-{context.attempt}-gate",
                contract_id=context.unit["contract_id"],
                work_unit_id=context.unit["unit_id"],
                execution_id=context.execution_id,
                checks=checks,
            )

        return WorkResult(
            outcome="succeeded" if bool(result.get("passed")) else "failed",
            summary=(
                f"Geometry sample {sample_id} strict-passed at {result.get('score', 0):.1f}"
                if result.get("passed")
                else f"Geometry sample {sample_id} stopped at {result.get('score', 0):.1f}"
            ),
            outputs=[{"artifact_id": artifact_id} for artifact_id in registered],
            evidence=[{
                "score": result.get("score"),
                "passed": bool(result.get("passed")),
                "stop_reason": result.get("stop_reason"),
                "attempts": len(result.get("attempts") or []),
                "result": str(job_dir / "result.json"),
            }],
            error=None if result.get("passed") else json.dumps({
                "stop_reason": result.get("stop_reason"),
                "score": result.get("score"),
            }),
        )
