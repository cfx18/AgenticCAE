"""Run geometry-grounded Codex/AutoCAD campaigns with immutable trajectories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from string import Template
import subprocess
import sys
import time
from typing import Any

from cad_evoloop.ledger import RunLedger
from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root
from cad_evoloop.verification.export_core_console import export_dwg_core

from .geometry_score import (
    ACCEPTABLE_THRESHOLDS,
    DEFAULT_THRESHOLDS,
    PROTOCOL_ID,
    score_geometry_files,
)


DEFAULT_MODEL = "gpt-5.6-sol"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")


def _safe_manifest_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Manifest path escapes dataset root: {value}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_geometry_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "1.0" or not isinstance(value.get("samples"), list):
        raise ValueError(f"Unsupported geometry manifest: {path}")
    identifiers = [sample.get("sample_id") for sample in value["samples"]]
    if any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Geometry manifest sample identifiers must be non-empty and unique")
    return path, value


def stage_agent_inputs(manifest_path: Path, sample: dict[str, Any], job_dir: Path) -> list[Path]:
    """Copy only agent-visible files; ground truth is deliberately excluded."""
    root = manifest_path.parent
    input_dir = job_dir / "input_files"
    input_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for index, relative in enumerate(sample.get("input_images", []), start=1):
        source = _safe_manifest_path(root, relative)
        if source.suffix.casefold() not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported input image: {source}")
        destination = input_dir / f"input-{index:02d}{source.suffix.casefold()}"
        shutil.copy2(source, destination)
        images.append(destination)
    if not images:
        raise ValueError(f"Geometry sample has no input images: {sample['sample_id']}")
    task = {
        "schema_version": "1.0",
        "sample_id": sample["sample_id"],
        "dataset": sample["dataset"],
        "task": sample["task"],
        "category": sample.get("category"),
        "input_images": [path.relative_to(job_dir).as_posix() for path in images],
        "output_requirement": "One native, editable AutoCAD 3D solid in model space.",
    }
    (job_dir / "task.json").write_text(
        json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return images


def geometry_verdict(result: dict[str, Any], sample_id: str) -> dict[str, Any]:
    checks = result["checks"]
    metrics = result["metrics"]
    rubrics = [
        {
            "id": "watertight",
            "status": "passed" if checks["candidate_watertight"] else "failed",
            "actual": result["candidate_geometry"]["watertight"],
            "expected": True,
        },
        {
            "id": "voxel_iou",
            "status": "passed" if checks["voxel_iou"] else "failed",
            "actual": metrics["voxel_iou"],
            "minimum": DEFAULT_THRESHOLDS["voxel_iou_min"],
        },
        {
            "id": "normalized_chamfer",
            "status": "passed" if checks["normalized_chamfer"] else "failed",
            "actual": metrics["normalized_chamfer"],
            "maximum": DEFAULT_THRESHOLDS["normalized_chamfer_max"],
        },
        {
            "id": "bbox_relative_error",
            "status": "passed" if checks["bbox_relative_error"] else "failed",
            "actual": metrics["bbox_relative_error"],
            "maximum": DEFAULT_THRESHOLDS["bbox_relative_error_max"],
        },
        {
            "id": "volume_relative_error",
            "status": "passed" if checks["volume_relative_error"] else "failed",
            "actual": metrics["volume_relative_error"],
            "maximum": DEFAULT_THRESHOLDS["volume_relative_error_max"],
        },
    ]
    return {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "sample_id": sample_id,
        "passed": result["passed"],
        "quality_tier": result["quality_tier"],
        "score": result["score"],
        "coverage": result["coverage"],
        "checks": checks,
        "acceptable_checks": result["acceptable_checks"],
        "metrics": metrics,
        "mismatch": result["mismatch"],
        "candidate_geometry": result["candidate_geometry"],
        "ground_truth_geometry": result["ground_truth_geometry"],
        "thresholds": DEFAULT_THRESHOLDS,
        "acceptable_thresholds": ACCEPTABLE_THRESHOLDS,
        "alignment": result["alignment"],
        "rubrics": rubrics,
        "eqc": {
            "eqc": result["score"],
            "success": result["passed"],
            "coverage": result["coverage"],
        },
    }


def failed_geometry_verdict(sample_id: str, error: str, error_type: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "sample_id": sample_id,
        "passed": False,
        "score": 0.0,
        "coverage": 0.0,
        "error_type": error_type,
        "error": error,
        "checks": {},
        "rubrics": [],
        "eqc": {"eqc": 0.0, "success": False, "coverage": 0.0},
    }


def _source_paths(workspace: Path) -> list[Path]:
    return [
        workspace / ".agents/skills/autocad-image-modeling/SKILL.md",
        workspace / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py",
        workspace / "src/cad_evoloop/backends/autocad/audited.py",
        workspace / "src/cad_evoloop/backends/autocad/core_console.py",
        workspace / "src/cad_evoloop/evaluation/geometry_campaign.py",
        workspace / "src/cad_evoloop/evaluation/geometry_score.py",
        workspace / "src/cad_evoloop/evaluation/geometry_split.py",
        workspace / "src/cad_evoloop/verification/export_core_console.py",
        workspace / "evals/geometry-benchmarks/prompts/modeling.md",
        workspace / "evals/geometry-benchmarks/prompts/repair.md",
        workspace / "evals/geometry-benchmarks/protocol-v2.json",
    ]


def _prompt(
    template_path: Path,
    *,
    sample_id: str,
    run_id: str,
    attempt_id: str,
    candidate: Path,
    previous_candidate: Path | None = None,
    verdict: Path | None = None,
    latest_verdict: Path | None = None,
    reflection: Path | None = None,
) -> str:
    skill_path = project_root() / ".agents/skills/autocad-image-modeling/SKILL.md"
    return Template(template_path.read_text(encoding="utf-8")).substitute(
        sample_id=sample_id,
        run_id=run_id,
        attempt_id=attempt_id,
        candidate=candidate.as_posix(),
        previous_candidate=(previous_candidate or candidate).as_posix(),
        verdict=(verdict or candidate).as_posix(),
        latest_verdict=(latest_verdict or verdict or candidate).as_posix(),
        reflection=(reflection or candidate).as_posix(),
        skill_path=skill_path.as_posix(),
    )


def codex_command(
    executable: str,
    model: str,
    effort: str,
    job_dir: Path,
    images: list[Path],
    prompt: str,
    audit_path: Path,
    final_path: Path,
) -> list[str]:
    workspace = project_root()
    audited = workspace / "src/cad_evoloop/backends/autocad/audited.py"
    base_server = workspace / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py"
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--approve-for-me",
        "--model", model,
        "--cd", str(job_dir),
        "-c", f'model_reasoning_effort="{effort}"',
        "-c", 'mcp_servers.autocad.command="python"',
        "-c", f'mcp_servers.autocad.args=["{audited.as_posix()}"]',
        "-c", (
            "mcp_servers.autocad.env={"
            f'AUTOCAD_MCP_WORKSPACE="{workspace.as_posix()}",'
            f'AUTOCAD_MCP_AUDIT_PATH="{audit_path.as_posix()}",'
            f'AUTOCAD_MCP_BASE_SERVER="{base_server.as_posix()}"'
            "}"
        ),
        "-c", "mcp_servers.autocad.startup_timeout_sec=20",
        "-c", "mcp_servers.autocad.tool_timeout_sec=60",
    ]
    if images:
        command.append("--image")
        command.extend(str(path) for path in images)
    command.extend(["--json", "--output-last-message", str(final_path), prompt])
    return command


def _read_codex_events(path: Path) -> dict[str, Any]:
    thread_id = None
    usage: dict[str, Any] = {}
    errors = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id")
            elif event.get("type") == "turn.completed":
                usage = event.get("usage") or usage
            elif event.get("type") in {"error", "turn.failed"}:
                errors.append(event.get("message") or event.get("error"))
    return {"thread_id": thread_id, "usage": usage, "errors": errors}


def should_stop_repairs(
    *,
    passed: bool,
    timed_out: bool,
    return_code: int | None,
    has_candidate: bool,
    non_improving_attempts: int,
    stagnation_limit: int,
    elapsed_seconds: float,
    job_time_budget: int,
) -> bool:
    return (
        passed
        or timed_out
        or return_code not in (None, 0)
        or not has_candidate
        or non_improving_attempts >= stagnation_limit
        or elapsed_seconds >= job_time_budget
    )


def remaining_attempt_timeout(configured_timeout: int, remaining_budget: float) -> int:
    """Bound a Codex turn by both its configured timeout and the job budget."""
    return max(1, min(configured_timeout, int(max(1.0, remaining_budget))))


def run_geometry_job(
    *,
    manifest_path: Path,
    sample: dict[str, Any],
    campaign: str,
    model: str,
    effort: str,
    executable: str,
    timeout: int,
    max_attempts: int,
    stagnation_limit: int,
    job_time_budget: int,
    score_samples: int,
    voxel_resolution: int,
    split_path: Path | None = None,
) -> dict[str, Any]:
    workspace = project_root()
    eval_root = workspace / "evals/geometry-benchmarks"
    campaign_dir = eval_root / "batch" / campaign
    sample_slug = slug(sample["sample_id"])
    base_job_dir = campaign_dir / sample_slug / slug(model)
    if base_job_dir.exists() and (base_job_dir / "result.json").is_file():
        return json.loads((base_job_dir / "result.json").read_text(encoding="utf-8"))
    job_dir = base_job_dir
    retry_number = 0
    while job_dir.exists():
        retry_number += 1
        job_dir = base_job_dir.with_name(f"{base_job_dir.name}.retry-{retry_number:03d}")
    job_dir.mkdir(parents=True, exist_ok=True)
    images = stage_agent_inputs(manifest_path, sample, job_dir)
    ground_truth = _safe_manifest_path(manifest_path.parent, sample["ground_truth_step"])
    retry_suffix = f"-retry-{retry_number:03d}" if retry_number else ""
    run_id = f"{campaign}-{slug(model)}-{effort}{retry_suffix}"
    ledger = RunLedger(eval_root)
    ledger_sample_id = sample_slug
    ledger_sample_dir = eval_root / "samples" / ledger_sample_id
    ledger_sample_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job_dir / "task.json", ledger_sample_dir / "task_desc.json")
    run_dir = ledger.start(
        ledger_sample_id,
        run_id=run_id,
        agent={
            "system": "codex-cli",
            "agent_id": "evocad-geometry-batch",
            "model": model,
            "reasoning_effort": effort,
            "external_sample_id": sample["sample_id"],
        },
        source_paths=_source_paths(workspace),
        input_paths=[job_dir / "task.json", *images, *([split_path] if split_path else [])],
    )
    prompt_root = eval_root / "prompts"
    attempts = []
    best_score = -1.0
    best_attempt_id = None
    best_candidate = None
    best_verdict = None
    previous_candidate = None
    previous_verdict = None
    latest_verdict = None
    non_improving_attempts = 0
    job_started = time.perf_counter()

    for number in range(1, max_attempts + 1):
        attempt_id = ledger.add_attempt(
            run_dir,
            label="fresh-modeling" if number == 1 else "geometry-guided-repair",
            summary=(
                "Reconstruct native 3D geometry from the visible drawing"
                if number == 1 else "Repair the best candidate from structured geometry feedback"
            ),
        )
        attempt_dir = job_dir / "attempts" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        candidate = job_dir / f"candidate.{attempt_id}.dwg"
        candidate_stl = attempt_dir / "candidate.stl"
        verdict_path = attempt_dir / "geometry-verdict.json"
        reflection_path = attempt_dir / "reflection.json"
        events_path = attempt_dir / "codex-events.jsonl"
        stderr_path = attempt_dir / "codex-stderr.log"
        final_path = attempt_dir / "codex-final.txt"
        audit_path = attempt_dir / "mcp-audit.jsonl"
        prompt = _prompt(
            prompt_root / ("modeling.md" if number == 1 else "repair.md"),
            sample_id=sample["sample_id"],
            run_id=run_id,
            attempt_id=attempt_id,
            candidate=candidate,
            previous_candidate=previous_candidate,
            verdict=previous_verdict,
            latest_verdict=latest_verdict,
            reflection=reflection_path,
        )
        command = codex_command(
            executable, model, effort, job_dir, images, prompt, audit_path, final_path,
        )
        attempt_timeout = remaining_attempt_timeout(
            timeout,
            job_time_budget - (time.perf_counter() - job_started),
        )
        started = time.perf_counter()
        timed_out = False
        return_code = None
        try:
            with events_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open(
                "w", encoding="utf-8", newline="\n",
            ) as stderr:
                completed = subprocess.run(
                    command,
                    cwd=job_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=attempt_timeout,
                    check=False,
                )
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            stderr_path.write_text(
                stderr_path.read_text(encoding="utf-8", errors="replace")
                + f"\nTimed out after {attempt_timeout} seconds\n",
                encoding="utf-8",
            )
        event_data = _read_codex_events(events_path)
        for path, role in (
            (events_path, "codex-events"),
            (stderr_path, "codex-stderr"),
            (final_path, "codex-final"),
            (audit_path, "mcp-audit"),
            (reflection_path, "reflection"),
        ):
            if path.is_file():
                ledger.add_artifact(run_dir, attempt_id, path, role=role)
        ledger.ingest_mcp_audit(run_dir, audit_path)

        if not candidate.is_file():
            verdict = failed_geometry_verdict(
                sample["sample_id"],
                "Codex agent did not create the requested candidate DWG",
                "agent-output-missing",
            )
        else:
            ledger.add_artifact(run_dir, attempt_id, candidate, role="candidate")
            try:
                export_dwg_core(candidate, candidate_stl, timeout=min(timeout, 180))
                ledger.add_artifact(run_dir, attempt_id, candidate_stl, role="candidate-mesh")
                raw_score = score_geometry_files(
                    candidate_stl,
                    ground_truth,
                    sample_count=score_samples,
                    voxel_resolution=voxel_resolution,
                )
                verdict = geometry_verdict(raw_score, sample["sample_id"])
            except Exception as exc:
                verdict = failed_geometry_verdict(
                    sample["sample_id"], repr(exc), "geometry-verifier-error",
                )
        verdict_path.write_text(
            json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        result = ledger.finish(run_dir, attempt_id, verdict_path)
        score = float(verdict["score"])
        attempt = {
            "attempt_id": attempt_id,
            "attempt_number": number,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "return_code": return_code,
            "timed_out": timed_out,
            "score": score,
            "passed": verdict["passed"],
            "verdict": str(verdict_path),
            **event_data,
        }
        attempts.append(attempt)
        improved = candidate.is_file() and score > best_score
        if improved:
            best_score = score
            best_attempt_id = attempt_id
            best_candidate = candidate
            best_verdict = verdict_path
            shutil.copy2(candidate, job_dir / "candidate.dwg")
            if candidate_stl.is_file():
                shutil.copy2(candidate_stl, job_dir / "candidate.stl")
            shutil.copy2(verdict_path, job_dir / "geometry-verdict.json")
            non_improving_attempts = 0
        else:
            non_improving_attempts += 1
        previous_candidate = best_candidate
        previous_verdict = best_verdict
        latest_verdict = verdict_path
        if should_stop_repairs(
            passed=verdict["passed"],
            timed_out=timed_out,
            return_code=return_code,
            has_candidate=previous_candidate is not None,
            non_improving_attempts=non_improving_attempts,
            stagnation_limit=stagnation_limit,
            elapsed_seconds=time.perf_counter() - job_started,
            job_time_budget=job_time_budget,
        ):
            break

    selected = ledger.select_attempt(run_dir, best_attempt_id) if best_attempt_id else result
    final = {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "campaign": campaign,
        "sample_id": sample["sample_id"],
        "ledger_sample_id": ledger_sample_id,
        "run_id": run_id,
        "model": model,
        "reasoning_effort": effort,
        "status": selected["status"],
        "score": best_score if best_attempt_id else 0.0,
        "passed": selected["status"] == "passed",
        "selected_attempt_id": best_attempt_id,
        "attempts": attempts,
        "candidate_sha256": sha256_file(job_dir / "candidate.dwg") if best_candidate else None,
        "ground_truth_sha256": sha256_file(ground_truth),
        "ledger_run": str(run_dir),
        "job_dir": str(job_dir),
        "integrity": ledger.verify_integrity(run_dir),
    }
    (job_dir / "result.json").write_text(
        json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return final


def build_geometry_campaign_manifest(
    manifest_path: Path,
    samples: list[dict[str, Any]],
    campaign: str,
    models: list[str],
    effort: str,
    max_attempts: int,
    stagnation_limit: int,
    job_time_budget: int,
    score_samples: int,
    voxel_resolution: int,
    split_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    jobs = []
    for sample in samples:
        ground_truth = _safe_manifest_path(manifest_path.parent, sample["ground_truth_step"])
        for model in models:
            jobs.append({
                "sample_id": sample["sample_id"],
                "model": model,
                "ground_truth_sha256": sha256_file(ground_truth),
            })
    payload = {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "campaign_id": campaign,
        "source_manifest_sha256": sha256_file(manifest_path),
        "models": [{"name": model, "reasoning_effort": effort} for model in models],
        "execution": {
            "max_attempts": max_attempts,
            "stagnation_limit": stagnation_limit,
            "job_time_budget_seconds": job_time_budget,
            "surface_samples": score_samples,
            "voxel_resolution": voxel_resolution,
        },
        "jobs": jobs,
    }
    if split_binding is not None:
        payload["benchmark_split"] = split_binding
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def run_geometry_campaign(
    manifest: str | Path,
    *,
    campaign: str,
    models: list[str] | None = None,
    sample_ids: set[str] | None = None,
    effort: str = "medium",
    max_attempts: int = 5,
    stagnation_limit: int = 2,
    job_time_budget: int = 3600,
    timeout: int = 1800,
    max_jobs: int | None = None,
    score_samples: int = 20000,
    voxel_resolution: int = 64,
    dry_run: bool = False,
    executable: str | None = None,
    split_file: str | Path | None = None,
    split_name: str | None = None,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if stagnation_limit < 1 or job_time_budget < 1:
        raise ValueError("stagnation_limit and job_time_budget must be at least 1")
    if timeout < 1 or score_samples < 1 or voxel_resolution < 16:
        raise ValueError("timeout and score_samples must be positive; voxel_resolution must be at least 16")
    if max_jobs is not None and max_jobs < 1:
        raise ValueError("max_jobs must be at least 1")
    manifest_path, value = load_geometry_manifest(manifest)
    models = models or [DEFAULT_MODEL]
    split_binding = None
    split_path = None
    if bool(split_file) != bool(split_name):
        raise ValueError("split_file and split_name must be provided together")
    if split_file:
        if sample_ids is not None:
            raise ValueError("sample_ids cannot be combined with a benchmark split")
        from .geometry_split import validate_geometry_split

        split_path = Path(split_file).resolve()
        split_payload = json.loads(split_path.read_text(encoding="utf-8"))
        scorable_ids = [
            sample["sample_id"] for sample in value["samples"] if sample.get("ground_truth_step")
        ]
        validate_geometry_split(split_payload, sample_ids=scorable_ids)
        if split_payload["source_manifest_sha256"] != sha256_file(manifest_path):
            raise ValueError("Benchmark split was created for a different source manifest")
        if split_name == "cost_pilot":
            selected_ids = split_payload["cost_pilot"]["sample_ids"]
        elif split_name in split_payload["splits"]:
            selected_ids = split_payload["splits"][split_name]
        else:
            raise ValueError(f"Unknown benchmark split name: {split_name}")
        sample_ids = set(selected_ids)
        split_binding = {
            "name": split_name,
            "split_sha256": split_payload["split_sha256"],
            "source_sample_ids_sha256": split_payload["source_sample_ids_sha256"],
        }
    samples = [
        sample for sample in value["samples"]
        if sample.get("ground_truth_step")
        and (sample_ids is None or sample["sample_id"] in sample_ids)
    ]
    unknown = (sample_ids or set()) - {sample["sample_id"] for sample in samples}
    if unknown:
        raise ValueError(f"Unknown or unscorable geometry samples: {sorted(unknown)}")
    jobs = [(sample, model) for sample in samples for model in models]
    if max_jobs is not None:
        jobs = jobs[:max_jobs]
    scheduled_samples = list({sample["sample_id"]: sample for sample, _ in jobs}.values())
    workspace = project_root()
    campaign_dir = workspace / "evals/geometry-benchmarks/batch" / campaign
    campaign_dir.mkdir(parents=True, exist_ok=True)
    campaign_manifest = build_geometry_campaign_manifest(
        manifest_path,
        scheduled_samples,
        campaign,
        list(dict.fromkeys(model for _, model in jobs)),
        effort,
        max_attempts,
        stagnation_limit,
        job_time_budget,
        score_samples,
        voxel_resolution,
        split_binding,
    )
    campaign_manifest_path = campaign_dir / "campaign-manifest.json"
    if campaign_manifest_path.is_file():
        existing = json.loads(campaign_manifest_path.read_text(encoding="utf-8"))
        if existing != campaign_manifest:
            raise ValueError(f"Campaign manifest is immutable and differs: {campaign_manifest_path}")
    else:
        campaign_manifest_path.write_text(
            json.dumps(campaign_manifest, indent=2) + "\n", encoding="utf-8",
        )
    plan = {
        "campaign": campaign,
        "protocol": PROTOCOL_ID,
        "manifest_sha256": campaign_manifest["manifest_sha256"],
        "jobs": [{"sample_id": sample["sample_id"], "model": model} for sample, model in jobs],
    }
    (campaign_dir / "plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    if dry_run:
        return {**plan, "status": "dry-run"}
    executable = executable or shutil.which("codex")
    if not executable:
        raise FileNotFoundError("codex executable was not found")
    results_path = campaign_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    completed = {(item["sample_id"], item["model"]) for item in results}
    for sample, model in jobs:
        if (sample["sample_id"], model) in completed:
            continue
        result = run_geometry_job(
            manifest_path=manifest_path,
            sample=sample,
            campaign=campaign,
            model=model,
            effort=effort,
            executable=executable,
            timeout=timeout,
            max_attempts=max_attempts,
            stagnation_limit=stagnation_limit,
            job_time_budget=job_time_budget,
            score_samples=score_samples,
            voxel_resolution=voxel_resolution,
            split_path=split_path,
        )
        results.append(result)
        results_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
    summary = {
        "campaign": campaign,
        "jobs": len(results),
        "passed": sum(bool(item["passed"]) for item in results),
        "mean_score": round(sum(float(item["score"]) for item in results) / len(results), 2)
        if results else None,
        "results": str(results_path),
    }
    (campaign_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return summary
