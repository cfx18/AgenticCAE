"""Run frozen geometry evaluations through the durable project-agent boundary."""

from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

from cad_evoloop.agent import (
    ArtifactRequirement,
    EngineeringPlan,
    ProjectKernel,
    ProjectStore,
    StageContract,
    WorkUnitSpec,
    apply_plan,
)
from cad_evoloop.agent.executors import (
    GeometryCampaignExecutor,
    GeometryCampaignExecutorConfig,
    HumanClarificationExecutor,
)
from cad_evoloop.evaluation.geometry_campaign import (
    DECISION_RETRY_LIMIT,
    load_geometry_manifest,
    slug,
)
from cad_evoloop.evaluation.review_feedback import load_human_feedback
from cad_evoloop.evaluation.reconstruction_ir import IR_MODES
from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root


AGENT_GEOMETRY_PROTOCOL = "evocad-agent-geometry-v1"
AGENT_CONDITION = "durable-kernel-boolean-lineage-v4"
HUMAN_FEEDBACK_CONDITION = "durable-kernel-human-feedback-checkpoint-v2"
ORACLE_CONDITIONS = {
    "perception": "durable-kernel-gt-oracle-perception-v1",
    "plan": "durable-kernel-gt-oracle-plan-v1",
}
IR_CONDITIONS = {
    "forced_ir": "durable-kernel-forced-reconstruction-ir-v1",
    "specialist_ir": "durable-kernel-specialist-reconstruction-ir-v1",
    "oracle_ir": "durable-kernel-oracle-reconstruction-ir-v1",
}
GEOMETRY_WORK_UNIT_MAX_ATTEMPTS = 2
GEOMETRY_DISTRIBUTIONS = ("cadquery-ocp", "numpy", "scipy", "trimesh")


def _canonical_hash(value: dict[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_frozen_selection(path: str | Path) -> tuple[Path, dict[str, Any]]:
    selection_path = Path(path).resolve()
    value = json.loads(selection_path.read_text(encoding="utf-8"))
    if value.get("kind") != "frozen-agent-evaluation-selection":
        raise ValueError("Unsupported agent evaluation selection")
    if value.get("sample_count") != len(value.get("sample_ids", [])):
        raise ValueError("Frozen selection sample count does not match its identifiers")
    if len(value["sample_ids"]) != len(set(value["sample_ids"])):
        raise ValueError("Frozen selection sample identifiers must be unique")
    if value.get("selection_sha256") != _canonical_hash(value, "selection_sha256"):
        raise ValueError("Frozen selection digest mismatch")
    source_split = selection_path.parent / value["source_split"]
    if sha256_file(source_split) != value["source_split_sha256"]:
        raise ValueError("Frozen selection source split digest mismatch")
    return selection_path, value


def _agent_source_hashes(workspace: Path) -> dict[str, str]:
    paths = sorted((workspace / "src/cad_evoloop/agent").rglob("*.py"))
    paths.extend(sorted((workspace / "src/cad_evoloop/agent/models").glob("*.mjs")))
    paths.extend([
        workspace / "src/cad_evoloop/evaluation/geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/geometry_features.py",
        workspace / "src/cad_evoloop/evaluation/agent_geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/detached_campaign.py",
        workspace / "src/cad_evoloop/evaluation/review_feedback.py",
        workspace / "src/cad_evoloop/evaluation/gt_trajectory.py",
        workspace / "src/cad_evoloop/evaluation/reconstruction_ir.py",
        workspace / "src/cad_evoloop/backends/autocad/topology.py",
        workspace / "src/cad_evoloop/backends/autocad/core_console.py",
        workspace / "src/cad_evoloop/backends/autocad/audited.py",
        workspace / "mcp/autocad-topology/EvoCadTopology.cs",
        workspace / ".agents/skills/autocad-image-modeling/SKILL.md",
        workspace / "evals/geometry-benchmarks/protocol-v2.json",
        workspace / "evals/geometry-benchmarks/agent-loop-v3.json",
        workspace / "evals/geometry-benchmarks/prompts/modeling.md",
        workspace / "evals/geometry-benchmarks/prompts/repair.md",
        workspace / "evals/geometry-benchmarks/prompts/adjudicate.md",
        workspace / "evals/geometry-benchmarks/prompts/modeling-ir.md",
        workspace / "evals/geometry-benchmarks/prompts/repair-ir.md",
        workspace / "evals/geometry-benchmarks/human-feedback-v1.json",
        workspace / "evals/geometry-benchmarks/gt-attribution-v1.json",
        workspace / "evals/geometry-benchmarks/ir-ablation-v1.json",
        workspace / "src/cad_evoloop/evaluation/schemas/reconstruction-ir.schema.json",
    ])
    return {
        path.relative_to(workspace).as_posix(): sha256_file(path)
        for path in paths
        if path.is_file()
    }


def collect_runtime_environment(executable: str | None = None, transport: Any = None) -> dict[str, Any]:
    """Capture the runtime identity that can change an evaluation result."""
    packages = {}
    for distribution in GEOMETRY_DISTRIBUTIONS:
        try:
            packages[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            packages[distribution] = None
    codex_command = executable or shutil.which("codex") or "codex"
    try:
        if transport is not None:
            raise OSError("Codex CLI is not used by this transport")
        completed = subprocess.run(
            [codex_command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        codex_version = (completed.stdout or completed.stderr).strip() or None
    except (OSError, subprocess.TimeoutExpired):
        codex_version = None
    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": Path(sys.executable).resolve().as_posix(),
        },
        "platform": platform.platform(),
        "packages": packages,
        "codex": {"command": None if transport else codex_command, "version": codex_version},
        **({"transport": transport.runtime_identity} if transport else {}),
    }


def require_geometry_environment(environment: dict[str, Any]) -> None:
    missing = [
        name for name, version in environment["packages"].items() if version is None
    ]
    if missing:
        raise RuntimeError(
            "Geometry verifier preflight failed; missing distributions: "
            + ", ".join(missing)
            + ". Install with `pip install -e .[geometry]`."
        )
    from cad_evoloop.evaluation.geometry_score import _dependencies

    _dependencies()
    if not environment.get("transport", {}).get("version") and environment["codex"]["version"] is None:
        raise RuntimeError("Codex CLI preflight failed; `codex --version` did not succeed")


def build_agent_campaign_manifest(
    *,
    manifest_path: Path,
    selection_path: Path,
    selection: dict[str, Any],
    campaign: str,
    model: str,
    effort: str,
    timeout: int,
    max_iterations: int,
    stagnation_limit: int,
    job_time_budget: int,
    score_samples: int,
    voxel_resolution: int,
    runtime_environment: dict[str, Any],
    effective_sample_ids: list[str] | None = None,
    human_feedback_binding: dict[str, Any] | None = None,
    oracle_binding: dict[str, Any] | None = None,
    reconstruction_mode: str = "baseline",
) -> dict[str, Any]:
    workspace = project_root()
    effective_sample_ids = effective_sample_ids or selection["sample_ids"]
    value = {
        "schema_version": "1.0",
        "protocol": AGENT_GEOMETRY_PROTOCOL,
        "agent_condition": (
            IR_CONDITIONS[reconstruction_mode] if reconstruction_mode != "baseline" else
            ORACLE_CONDITIONS[oracle_binding["level"]] if oracle_binding else
            HUMAN_FEEDBACK_CONDITION if human_feedback_binding else AGENT_CONDITION
        ),
        "campaign_id": campaign,
        "model": {"name": model, "reasoning_effort": effort},
        "selection": {
            "path": selection_path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(selection_path),
            "selection_sha256": selection["selection_sha256"],
            "source_sample_count": selection["sample_count"],
            "sample_count": len(effective_sample_ids),
            "sample_ids": effective_sample_ids,
        },
        "source_manifest_sha256": sha256_file(manifest_path),
        "execution": {
            "timeout_seconds": timeout,
            "max_iterations_safety": max_iterations,
            "stagnation_advisory": stagnation_limit,
            "job_time_budget_seconds": job_time_budget,
            "surface_samples": score_samples,
            "voxel_resolution": voxel_resolution,
            "reconstruction_mode": reconstruction_mode,
            "ir_gate_required": reconstruction_mode != "baseline",
            "image_visibility": (
                "same_thread_builder_only" if reconstruction_mode == "forced_ir" else
                "ir_builder_only" if reconstruction_mode == "specialist_ir" else
                "none" if reconstruction_mode == "oracle_ir" else
                "cad_agent"
            ),
            "project_isolation": "one-project-per-sample",
            "decision_transport_retry_limit": DECISION_RETRY_LIMIT,
            "attempt_recovery": {
                "protocol": "geometry-attempt-checkpoint-v1",
                "stages": ["action_running", "action_completed", "verifier_completed"],
                "preserve_interrupted_traces": True,
            },
            "boolean_face_lineage": {
                "protocol": "evocad-boolean-face-lineage-v2",
                "capture": "native_topology_before_and_after_each_core_job",
                "operation_metadata_is_non_restrictive": True,
            },
        },
        "runtime_environment": runtime_environment,
        "agent_source_hashes": _agent_source_hashes(workspace),
    }
    if human_feedback_binding is not None:
        value["human_feedback"] = human_feedback_binding
    if oracle_binding is not None:
        value["oracle_context"] = oracle_binding
    value["campaign_manifest_sha256"] = _canonical_hash(value, "campaign_manifest_sha256")
    return value


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _create_sample_project(
    *,
    projects_root: Path,
    campaign: str,
    sample: dict[str, Any],
    manifest_path: Path,
    model: str,
    sample_feedback: dict[str, Any] | None = None,
    sample_feedback_path: Path | None = None,
    sample_oracle: dict[str, Any] | None = None,
    sample_oracle_path: Path | None = None,
    reconstruction_mode: str = "baseline",
) -> ProjectStore:
    project_id = slug(sample["sample_id"])
    project_dir = projects_root / project_id
    if project_dir.is_dir():
        return ProjectStore(projects_root, project_id)
    store = ProjectStore.create(
        projects_root,
        project_id,
        f"Reconstruct and strictly verify geometry sample {sample['sample_id']}",
        metadata={
            "campaign": campaign,
            "sample_id": sample["sample_id"],
            "model": model,
            "agent_condition": (
                IR_CONDITIONS[reconstruction_mode] if reconstruction_mode != "baseline" else
                ORACLE_CONDITIONS[sample_oracle["oracle_level"]] if sample_oracle else
                HUMAN_FEEDBACK_CONDITION if sample_feedback else AGENT_CONDITION
            ),
            "reconstruction_mode": reconstruction_mode,
        },
    )
    input_ids = []
    for index, relative in enumerate(sample["input_images"], 1):
        artifact_id = f"input-{index}"
        store.register_artifact(
            manifest_path.parent / relative,
            artifact_id=artifact_id,
            kind="design_evidence",
            metadata={"sample_id": sample["sample_id"], "visible_to_agent": True},
            actor="campaign",
        )
        input_ids.append(artifact_id)
    feedback_id = None
    if sample_feedback is not None:
        if sample_feedback_path is None:
            raise ValueError("Sample feedback path is required for human feedback")
        feedback_id = "human-feedback"
        store.register_artifact(
            sample_feedback_path,
            artifact_id=feedback_id,
            kind="human_feedback",
            metadata={
                "sample_id": sample["sample_id"],
                "route": sample_feedback["route"],
                "visible_to_agent": True,
            },
            actor="campaign",
        )
        input_ids.append(feedback_id)
    oracle_id = None
    if sample_oracle is not None:
        if sample_oracle_path is None:
            raise ValueError("Sample oracle path is required for an oracle intervention")
        oracle_id = "evaluator-oracle"
        store.register_artifact(
            sample_oracle_path,
            artifact_id=oracle_id,
            kind="evaluator_oracle",
            metadata={
                "sample_id": sample["sample_id"],
                "oracle_level": sample_oracle["oracle_level"],
                "visible_to_agent": True,
                "evaluation_only_intervention": True,
            },
            actor="campaign",
        )
        input_ids.append(oracle_id)
    requirements = [ArtifactRequirement("design_evidence", len(sample["input_images"]))]
    if feedback_id:
        requirements.append(ArtifactRequirement("human_feedback"))
    if oracle_id:
        requirements.append(ArtifactRequirement("evaluator_oracle"))
    contract = StageContract(
        contract_id="geometry-strict-gate-v1",
        stage="geometry",
        input_requirements=tuple(requirements),
        output_requirements=(ArtifactRequirement("cad_model"),),
        verifier_ids=("native-geometry", "strict-geometry"),
        description="Native candidate exists and strict geometry metrics pass",
    )
    dependencies = ()
    work_units = []
    if sample_feedback and sample_feedback["route"] == "human_clarification":
        clarification = WorkUnitSpec(
            unit_id="human-clarification",
            kind="human_clarification",
            phase="requirements",
            title="Human clarification",
            description="Wait for missing or ambiguous engineering requirements",
            acceptance_criteria=("A bound human clarification response is available",),
            input_artifact_ids=tuple(input_ids),
            max_attempts=2,
            parameters={
                "sample_id": sample["sample_id"],
                "feedback_artifact_id": feedback_id,
            },
        )
        work_units.append(clarification)
        dependencies = (clarification.unit_id,)
    unit = WorkUnitSpec(
        unit_id="geometry-reconstruction",
        kind="geometry_campaign",
        phase="geometry",
        title="Geometry reconstruction",
        description="Run the evidence-bound Codex and AutoCAD reconstruction loop",
        acceptance_criteria=("Strict geometry contract passes",),
        contract_id=contract.contract_id,
        input_artifact_ids=tuple(input_ids),
        dependencies=dependencies,
        # The inner geometry loop owns modeling iterations. This second outer
        # attempt is reserved for one durable recovery after host interruption.
        max_attempts=GEOMETRY_WORK_UNIT_MAX_ATTEMPTS,
        parameters={
            "sample_id": sample["sample_id"],
            "reconstruction_mode": reconstruction_mode,
        },
    )
    work_units.append(unit)
    apply_plan(store, EngineeringPlan(
        plan_id=(
            f"geometry-agent-plan-{reconstruction_mode}-v1"
            if reconstruction_mode != "baseline" else
            f"geometry-agent-plan-gt-oracle-{sample_oracle['oracle_level']}-v1"
            if sample_oracle else
            "geometry-agent-plan-human-feedback-v1" if sample_feedback else
            "geometry-agent-plan-v1"
        ),
        objective="Produce one native editable solid that strict-matches evaluator geometry",
        work_units=tuple(work_units),
        contracts=(contract,),
        rationale=(
            "Validated reconstruction IR gate with condition-specific image isolation"
            if reconstruction_mode != "baseline" else
            "Hash-bound GT oracle intervention for causal failure attribution"
            if sample_oracle else
            "Hash-bound human review feedback with a clarification gate"
            if sample_feedback else
            "Semantic-parity bridge from the recorded v2 loop into the durable kernel"
        ),
    ), actor="campaign")
    return store


def run_agent_geometry_campaign(
    manifest: str | Path,
    selection: str | Path,
    *,
    campaign: str,
    model: str = "gpt-5.6-sol",
    effort: str = "medium",
    executable: str | None = None,
    timeout: int = 900,
    max_iterations: int = 12,
    stagnation_limit: int = 2,
    job_time_budget: int = 3600,
    score_samples: int = 20000,
    voxel_resolution: int = 64,
    max_jobs: int | None = None,
    dry_run: bool = False,
    human_feedback: str | Path | None = None,
    feedback_only: bool = False,
    oracle_context: str | Path | None = None,
    oracle_level: str | None = None,
    reconstruction_mode: str = "baseline",
    transport: Any = None,
) -> dict[str, Any]:
    if max_jobs is not None and max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    if reconstruction_mode not in IR_MODES:
        raise ValueError(f"Unsupported reconstruction mode: {reconstruction_mode}")
    if bool(oracle_context) != bool(oracle_level):
        raise ValueError("oracle_context and oracle_level must be provided together")
    if oracle_context and human_feedback:
        raise ValueError("Oracle and human-feedback interventions must run in separate campaigns")
    if reconstruction_mode == "oracle_ir" and (
        oracle_context is None or oracle_level != "perception"
    ):
        raise ValueError("oracle_ir requires --oracle-context with --oracle-level perception")
    if reconstruction_mode in {"forced_ir", "specialist_ir"} and oracle_context:
        raise ValueError(f"{reconstruction_mode} cannot be combined with oracle context")
    if reconstruction_mode != "baseline" and human_feedback:
        raise ValueError("IR ablation conditions cannot be combined with human feedback")
    runtime_environment = (
        collect_runtime_environment(executable, transport) if transport
        else collect_runtime_environment(executable)
    )
    if not dry_run:
        require_geometry_environment(runtime_environment)
    manifest_path, manifest_value = load_geometry_manifest(manifest)
    selection_path, selection_value = load_frozen_selection(selection)
    if sha256_file(manifest_path) != selection_value["source_manifest_sha256"]:
        raise ValueError("Frozen selection was created for a different geometry manifest")
    by_id = {sample["sample_id"]: sample for sample in manifest_value["samples"]}
    missing = [sample_id for sample_id in selection_value["sample_ids"] if sample_id not in by_id]
    if missing:
        raise ValueError(f"Frozen selection references missing samples: {missing}")
    oracle_path = None
    oracle_value = None
    oracle_binding = None
    if oracle_context is not None:
        from cad_evoloop.evaluation.gt_trajectory import (
            ORACLE_LEVELS,
            load_oracle_context,
            validate_oracle_packet,
        )

        if oracle_level not in ORACLE_LEVELS:
            raise ValueError(f"Unsupported oracle level: {oracle_level}")
        oracle_path, oracle_value = load_oracle_context(oracle_context)
        if oracle_value["source_manifest_sha256"] != sha256_file(manifest_path):
            raise ValueError("Oracle context was produced for a different geometry manifest")
        missing_oracles = set(selection_value["sample_ids"]) - set(oracle_value["samples"])
        if missing_oracles:
            raise ValueError(f"Oracle context is missing selected samples: {sorted(missing_oracles)}")
        for sample_id in selection_value["sample_ids"]:
            validate_oracle_packet(
                oracle_value["samples"][sample_id][str(oracle_level)],
                sample_id,
                str(oracle_level),
            )
        oracle_binding = {
            "path": oracle_path.relative_to(project_root()).as_posix(),
            "sha256": sha256_file(oracle_path),
            "oracle_manifest_sha256": oracle_value["oracle_manifest_sha256"],
            "level": oracle_level,
            "evaluation_only_intervention": True,
        }
    feedback_path = None
    feedback_value = None
    feedback_binding = None
    if human_feedback is not None:
        feedback_path, feedback_value = load_human_feedback(human_feedback)
        if (
            feedback_value["source"].get("source_manifest_sha256")
            != sha256_file(manifest_path)
        ):
            raise ValueError("Human feedback was produced for a different geometry manifest")
        unknown_feedback = set(feedback_value["sample_ids"]) - set(by_id)
        if unknown_feedback:
            raise ValueError(
                f"Human feedback references unknown samples: {sorted(unknown_feedback)}"
            )
        workspace = project_root()
        try:
            relative_feedback = feedback_path.relative_to(workspace).as_posix()
        except ValueError as exc:
            raise ValueError("Human feedback must be stored inside the workspace") from exc
        feedback_binding = {
            "path": relative_feedback,
            "sha256": sha256_file(feedback_path),
            "feedback_manifest_sha256": feedback_value["feedback_manifest_sha256"],
            "review_bundle_sha256": feedback_value["source"]["review_bundle_sha256"],
            "review_ledger_sha256": feedback_value["source"]["review_ledger_sha256"],
            "review_ledger_head_sha256": feedback_value["source"][
                "review_ledger_head_sha256"
            ],
            "active_review_count": feedback_value["active_review_count"],
            "sample_count": feedback_value["sample_count"],
            "feedback_only": feedback_only,
        }
    elif feedback_only:
        raise ValueError("feedback_only requires a human feedback manifest")
    effective_sample_ids = list(selection_value["sample_ids"])
    if feedback_only:
        feedback_ids = {
            sample_id for sample_id, sample_feedback in feedback_value["samples"].items()
            if sample_feedback["route"] in {"human_clarification", "agent_repair"}
        }
        effective_sample_ids = [
            sample_id for sample_id in effective_sample_ids if sample_id in feedback_ids
        ]
        if not effective_sample_ids:
            raise ValueError("Human feedback does not overlap the frozen selection")
    campaign_dir = project_root() / "evals/geometry-benchmarks/batch" / campaign
    campaign_dir.mkdir(parents=True, exist_ok=True)
    campaign_manifest = build_agent_campaign_manifest(
        manifest_path=manifest_path,
        selection_path=selection_path,
        selection=selection_value,
        campaign=campaign,
        model=model,
        effort=effort,
        timeout=timeout,
        max_iterations=max_iterations,
        stagnation_limit=stagnation_limit,
        job_time_budget=job_time_budget,
        score_samples=score_samples,
        voxel_resolution=voxel_resolution,
        runtime_environment=runtime_environment,
        effective_sample_ids=effective_sample_ids,
        human_feedback_binding=feedback_binding,
        oracle_binding=oracle_binding,
        reconstruction_mode=reconstruction_mode,
    )
    campaign_manifest_path = campaign_dir / "agent-campaign-manifest.json"
    if campaign_manifest_path.is_file():
        if json.loads(campaign_manifest_path.read_text(encoding="utf-8")) != campaign_manifest:
            raise ValueError("Agent campaign manifest is immutable and differs")
    else:
        _write_json_atomic(campaign_manifest_path, campaign_manifest)
    plan = {
        "campaign": campaign,
        "jobs": [
            {
                "sample_id": sample_id,
                "project_id": slug(sample_id),
                "model": model,
                **({"reconstruction_mode": reconstruction_mode}
                   if reconstruction_mode != "baseline" else {}),
                **({"oracle_level": oracle_level} if oracle_level else {}),
                **({
                    "feedback_route": feedback_value["samples"][sample_id]["route"],
                } if feedback_value and sample_id in feedback_value["samples"] else {}),
            }
            for sample_id in effective_sample_ids
        ],
    }
    _write_json_atomic(campaign_dir / "agent-plan.json", plan)
    if dry_run:
        return {"dry_run": True, "campaign_manifest": campaign_manifest, **plan}

    results_path = campaign_dir / "agent-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    completed = {
        item["sample_id"] for item in results
        if item.get("work_unit_status") in {"succeeded", "failed"}
    }
    projects_root = campaign_dir / "projects"
    projects_root.mkdir(exist_ok=True)
    executor_config = GeometryCampaignExecutorConfig(
        manifest_path=manifest_path,
        campaign=campaign,
        model=model,
        reasoning_effort=effort,
        executable=executable,
        timeout_seconds=timeout,
        max_iterations=max_iterations,
        stagnation_limit=stagnation_limit,
        job_time_budget_seconds=job_time_budget,
        score_samples=score_samples,
        voxel_resolution=voxel_resolution,
        split_path=selection_path,
        reconstruction_mode=reconstruction_mode,
        transport=transport,
    )
    scheduled_this_run = 0
    feedback_dir = campaign_dir / "human-feedback"
    oracle_dir = campaign_dir / "oracle-context"
    for sample_id in effective_sample_ids:
        if sample_id in completed:
            continue
        if max_jobs is not None and scheduled_this_run >= max_jobs:
            break
        sample_feedback = (
            feedback_value["samples"].get(sample_id) if feedback_value else None
        )
        if sample_feedback and sample_feedback["route"] not in {
            "human_clarification", "agent_repair",
        }:
            sample_feedback = None
        sample_feedback_path = None
        if sample_feedback is not None:
            feedback_dir.mkdir(exist_ok=True)
            sample_feedback_path = feedback_dir / f"{slug(sample_id)}.json"
            _write_json_atomic(sample_feedback_path, sample_feedback)
        sample_oracle = None
        sample_oracle_path = None
        if oracle_value is not None:
            sample_oracle = oracle_value["samples"][sample_id][str(oracle_level)]
            oracle_dir.mkdir(exist_ok=True)
            sample_oracle_path = oracle_dir / f"{slug(sample_id)}-{oracle_level}.json"
            _write_json_atomic(sample_oracle_path, sample_oracle)
        store = _create_sample_project(
            projects_root=projects_root,
            campaign=campaign,
            sample=by_id[sample_id],
            manifest_path=manifest_path,
            model=model,
            sample_feedback=sample_feedback,
            sample_feedback_path=sample_feedback_path,
            sample_oracle=sample_oracle,
            sample_oracle_path=sample_oracle_path,
            reconstruction_mode=reconstruction_mode,
        )
        kernel = ProjectKernel(
            store,
            {
                "geometry_campaign": GeometryCampaignExecutor(store, executor_config),
                "human_clarification": HumanClarificationExecutor(store),
            },
        )
        kernel.recover_interrupted(actor="campaign")
        kernel.run(actor="campaign")
        state = store.load()
        unit = state["work_units"]["geometry-reconstruction"]
        clarification = state["work_units"].get("human-clarification")
        if unit["status"] == "failed" and state["status"] == "active":
            state = store.append(
                "project.failed",
                {"summary": unit["summary"] or unit["last_error"]},
                actor="campaign",
                idempotency_key="project.failed:geometry-work-unit",
            )
        evidence = unit["evidence"][-1] if unit["evidence"] else {}
        work_unit_status = unit["status"]
        if clarification and clarification["status"] == "blocked":
            evidence = clarification["evidence"][-1] if clarification["evidence"] else {}
            work_unit_status = "blocked"
        row = {
            "sample_id": sample_id,
            "project_id": store.project_id,
            "project_status": state["status"],
            "work_unit_status": work_unit_status,
            "passed": unit["status"] == "succeeded",
            "score": evidence.get("score", 0.0),
            "stop_reason": evidence.get("stop_reason"),
            "clarification_questions": evidence.get("questions", []),
            "attempts": evidence.get("attempts", 0),
            "result": evidence.get("result"),
            "project_events": state["last_sequence"],
            "project_integrity": store.verify(),
        }
        results = [item for item in results if item["sample_id"] != sample_id]
        results.append(row)
        _write_json_atomic(results_path, results)
        scheduled_this_run += 1
    summary = {
        "campaign": campaign,
        "sample_count": len(results),
        "planned_sample_count": len(effective_sample_ids),
        "complete": len(results) == len(effective_sample_ids) and all(
            item["work_unit_status"] in {"succeeded", "failed"} for item in results
        ),
        "strict_passes": sum(bool(item["passed"]) for item in results),
        "strict_pass_rate": (
            sum(bool(item["passed"]) for item in results) / len(results) if results else 0.0
        ),
        "infrastructure_integrity_failures": sum(
            not item["project_integrity"]["ok"] for item in results
        ),
        "human_clarification_required": sum(
            item["work_unit_status"] == "blocked" for item in results
        ),
    }
    _write_json_atomic(campaign_dir / "agent-summary.json", summary)
    return {"campaign_manifest": campaign_manifest, "results": results, "summary": summary}
