"""Run isolated AutoCAD modeling jobs through Codex across a model matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from string import Template
import subprocess
import sys
import time
import traceback
from typing import Any, Callable


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = EVAL_ROOT.parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))

from cad_evoloop.ledger import RunLedger
from cad_evoloop.evaluation import (
    build_campaign_manifest,
    evidence_qualified_completion,
    export_agent_inputs,
    visible_input_paths,
    write_immutable_manifest,
)
from cad_evoloop.protocol import build_diagnostic
from cad_evoloop.supervisor import AdaptiveSession
from cad_evoloop.verification.vlm.evaluate import evaluate_visual_gaps
from cad_evoloop.verification.vlm.render_scene import render_scene
from cad_evoloop.verification.render_core_console import render_dwg_core


DEFAULT_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5")
DEFAULT_SMOKE_SAMPLES = (
    "8fc225b8-0a4a-4e80-80e4-320ef6c5b9eb",  # dimensioned 2D mechanical
    "92dbe113-d7de-46ae-bfae-8ff7436058e6",  # single-solid 3D
    "256db834-9f8b-47a5-9fa3-b9698ddc7f57",  # architectural plans
)
SOURCE_PATHS = (
    WORKSPACE / ".agents/skills/autocad-image-modeling/SKILL.md",
    WORKSPACE / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py",
    WORKSPACE / "src/cad_evoloop/backends/autocad/audited.py",
    WORKSPACE / "src/cad_evoloop/backends/autocad/jobs.py",
    WORKSPACE / "src/cad_evoloop/backends/autocad/core_console.py",
    WORKSPACE / "src/cad_evoloop/verification/extract_autocad.py",
    WORKSPACE / "src/cad_evoloop/verification/extract_core_console.py",
    WORKSPACE / "src/cad_evoloop/verification/verify.py",
    WORKSPACE / "src/cad_evoloop/verification/render_core_console.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/evaluate.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/provider.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/render_scene.py",
    WORKSPACE / "src/cad_evoloop/verification/schemas/visual-verdict.schema.json",
    WORKSPACE / "src/cad_evoloop/evaluation/metrics.py",
    WORKSPACE / "src/cad_evoloop/ledger/ledger.py",
    EVAL_ROOT / "prompts/modeling.md",
    EVAL_ROOT / "prompts/repair.md",
    Path(__file__).resolve(),
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PROMPT_ROOT = EVAL_ROOT / "prompts"
SKILL_PATH = WORKSPACE / ".agents/skills/autocad-image-modeling/SKILL.md"
SKILL_SERVER_PATH = WORKSPACE / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py"
MCP_SERVER_PATH = WORKSPACE / "src/cad_evoloop/backends/autocad/audited.py"
VERIFIER_PATH = WORKSPACE / "src/cad_evoloop/verification/verify.py"


def activate_proposal(proposal_id: str) -> dict[str, Any]:
    """Point a batch at candidate sources without promoting them to production."""
    global PROMPT_ROOT, SKILL_PATH, MCP_SERVER_PATH, VERIFIER_PATH, SOURCE_PATHS
    proposal_dir = EVAL_ROOT / "improvement" / "proposals" / proposal_id
    manifest_path = proposal_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {"proposed", "gate-passed", "gate-rejected"}:
        raise ValueError(f"Proposal is not evaluable: {manifest.get('status')}")
    candidate_workspace = proposal_dir / "workspace"
    changed_files = set(manifest.get("changed_files") or ())
    if not changed_files:
        changed_files = {
            item["path"] for item in manifest["files"]
            if not item.get("before_sha256") or item.get("before_sha256") != item.get("after_sha256")
        }
    def component_for(item: dict[str, Any]) -> str:
        if item.get("component"):
            return str(item["component"])
        relative = item["path"]
        if "/prompts/" in relative:
            return "prompt"
        if relative.endswith("/SKILL.md"):
            return "skill"
        if relative.startswith("src/cad_evoloop/backends/autocad/"):
            return "mcp"
        if relative.startswith("src/cad_evoloop/verification/"):
            return "verifier"
        raise ValueError(f"Cannot infer proposal component for {relative}")

    changed_components = {
        component_for(item) for item in manifest["files"] if item["path"] in changed_files
    }
    if "prompt" in changed_components:
        PROMPT_ROOT = candidate_workspace / "evals/cad-1000-hours/prompts"
    if "skill" in changed_components:
        SKILL_PATH = candidate_workspace / ".agents/skills/autocad-image-modeling/SKILL.md"
    if "mcp" in changed_components:
        MCP_SERVER_PATH = candidate_workspace / "src/cad_evoloop/backends/autocad/audited.py"
    if "verifier" in changed_components:
        VERIFIER_PATH = candidate_workspace / "src/cad_evoloop/verification/verify.py"
    production_by_relative = {
        path.resolve().relative_to(WORKSPACE.resolve()).as_posix(): path for path in SOURCE_PATHS
    }
    effective_sources = []
    for item in manifest["files"]:
        relative = item["path"]
        effective_sources.append(
            candidate_workspace / relative
            if relative in changed_files
            else production_by_relative.get(relative, WORKSPACE / relative)
        )
    SOURCE_PATHS = tuple(effective_sources) + (Path(__file__).resolve(),)
    for path in (*SOURCE_PATHS, PROMPT_ROOT / "modeling.md", PROMPT_ROOT / "repair.md"):
        if not path.is_file():
            raise FileNotFoundError(path)
    return manifest


def activate_adaptive_session(session: AdaptiveSession) -> None:
    """Route every editable component to a complete isolated adaptive workspace."""
    global PROMPT_ROOT, SKILL_PATH, SKILL_SERVER_PATH, MCP_SERVER_PATH, VERIFIER_PATH, SOURCE_PATHS
    PROMPT_ROOT = session.path("evals/cad-1000-hours/prompts")
    SKILL_PATH = session.path(".agents/skills/autocad-image-modeling/SKILL.md")
    SKILL_SERVER_PATH = session.path(
        ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py"
    )
    MCP_SERVER_PATH = session.path("src/cad_evoloop/backends/autocad/audited.py")
    VERIFIER_PATH = session.path("src/cad_evoloop/verification/verify.py")
    SOURCE_PATHS = session.source_paths() + (Path(__file__).resolve(),)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")


def read_events(path: Path) -> dict[str, Any]:
    thread_id = None
    usage: dict[str, Any] = {}
    prohibited_errors = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id")
            if event.get("type") == "turn.completed":
                usage = event.get("usage") or usage
            if event.get("type") in {"error", "turn.failed"}:
                prohibited_errors.append(event.get("message") or event.get("error"))
    return {"thread_id": thread_id, "usage": usage, "errors": prohibited_errors}


def sample_inputs(sample_dir: Path) -> list[Path]:
    return visible_input_paths(sample_dir)


def prepare_job(sample_dir: Path, job_dir: Path) -> list[Path]:
    export_agent_inputs(sample_dir, job_dir)
    return sorted(
        path for path in (job_dir / "input_files").rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    ) if (job_dir / "input_files").is_dir() else []


def allocate_job_dir(campaign_dir: Path, sample_id: str, model: str) -> tuple[Path, int]:
    """Keep incomplete job artifacts and allocate a fresh directory for a retry."""
    sample_dir = campaign_dir / sample_id
    model_slug = slug(model)
    primary = sample_dir / model_slug
    if not primary.exists():
        return primary, 0
    retry = 1
    while True:
        candidate = sample_dir / f"{model_slug}.retry-{retry:03d}"
        if not candidate.exists():
            return candidate, retry
        retry += 1


def is_terminal_result(result: dict[str, Any]) -> bool:
    """Only stable results suppress a job during campaign resume."""
    return (
        result.get("status") != "harness-error"
        and not result.get("interrupted", False)
        and not result.get("timed_out", False)
        and result.get("return_code") in (None, 0)
    )


def has_verifier_infrastructure_failure(result: dict[str, Any]) -> bool:
    job_dir = result.get("job_dir")
    if not job_dir:
        return False
    verdict_path = Path(job_dir) / "verdict.json"
    if not verdict_path.is_file():
        return False
    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    return (
        verdict.get("error_type") == "verifier-infrastructure"
        or str(verdict.get("error", "")).startswith("Verifier failed with exit code")
    )


def load_resumable_results(results_path: Path) -> list[dict[str, Any]]:
    """Move transient results out of the score input while retaining their history."""
    if not results_path.is_file():
        return []
    results = json.loads(results_path.read_text(encoding="utf-8"))
    stable = [
        item for item in results
        if is_terminal_result(item) and not has_verifier_infrastructure_failure(item)
    ]
    retryable = [item for item in results if item not in stable]
    if retryable:
        history_path = results_path.with_name("retry-history.jsonl")
        with history_path.open("a", encoding="utf-8", newline="\n") as stream:
            for item in retryable:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
        results_path.write_text(
            json.dumps(stable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
    return stable


def prompt_for(sample_id: str, run_id: str, attempt_id: str, candidate: Path) -> str:
    geometry_checkpoint = candidate.with_name(f"{candidate.stem}.geometry.dwg")
    annotation_checkpoint = candidate.with_name(f"{candidate.stem}.annotated.dwg")
    return Template((PROMPT_ROOT / "modeling.md").read_text(encoding="utf-8")).substitute(
        sample_id=sample_id,
        run_id=run_id,
        attempt_id=attempt_id,
        skill_path=SKILL_PATH.as_posix(),
        geometry_checkpoint=geometry_checkpoint.as_posix(),
        annotation_checkpoint=annotation_checkpoint.as_posix(),
        candidate=candidate.as_posix(),
    )


def repair_prompt_for(
    sample_id: str,
    run_id: str,
    attempt_id: str,
    previous_candidate: Path,
    previous_verdict: Path,
    candidate: Path,
    reflection: Path,
    previous_diagnostic: Path | None = None,
) -> str:
    return Template((PROMPT_ROOT / "repair.md").read_text(encoding="utf-8")).substitute(
        sample_id=sample_id,
        run_id=run_id,
        attempt_id=attempt_id,
        previous_candidate=previous_candidate.as_posix(),
        previous_verdict=previous_verdict.as_posix(),
        candidate=candidate.as_posix(),
        reflection=reflection.as_posix(),
        previous_diagnostic=(previous_diagnostic or previous_verdict).as_posix(),
    )


def codex_command(
    executable: str,
    model: str,
    effort: str,
    job_dir: Path,
    images: list[Path],
    audit_path: Path,
    final_path: Path,
    prompt: str,
) -> list[str]:
    workspace = WORKSPACE.as_posix()
    audit = audit_path.as_posix()
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--approve-for-me",
        "--model",
        model,
        "--cd",
        str(job_dir),
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        'mcp_servers.autocad.command="python"',
        "-c",
        f'mcp_servers.autocad.args=["{MCP_SERVER_PATH.as_posix()}"]',
        "-c",
        f'mcp_servers.autocad.env={{AUTOCAD_MCP_WORKSPACE="{workspace}",AUTOCAD_MCP_AUDIT_PATH="{audit}",AUTOCAD_MCP_BASE_SERVER="{SKILL_SERVER_PATH.as_posix()}"}}',
        "-c",
        "mcp_servers.autocad.startup_timeout_sec=20",
        "-c",
        "mcp_servers.autocad.tool_timeout_sec=60",
    ]
    if images:
        command.append("--image")
        command.extend(str(path) for path in images)
    command.extend(["--json", "--output-last-message", str(final_path), prompt])
    return command


def reset_autocad_command_state() -> str | None:
    """Cancel any command left active by a failed agent before the next job."""
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        document = app.ActiveDocument
        if document.GetVariable("CMDNAMES"):
            document.SendCommand("\x1b\x1b\x1b")
            time.sleep(1)
        return str(document.GetVariable("CMDNAMES"))
    except Exception as exc:
        return f"reset-error: {exc!r}"
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def failed_verdict(path: Path, message: str, *, error_type: str | None = None) -> None:
    verdict = {
        "passed": False,
        "score": 0.0,
        "coverage": 0.0,
        "error": message,
    }
    if error_type:
        verdict["error_type"] = error_type
    path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")


def below_minimum_coverage(verdict: dict[str, Any], minimum: float) -> bool:
    return bool(verdict.get("passed")) and float(verdict.get("coverage", 0.0) or 0.0) < minimum


def should_select_checkpoint(candidate: Path, eqc: float, best_eqc: float) -> bool:
    """Prefer the first valid artifact at each strictly higher EQC level."""
    return candidate.is_file() and eqc > best_eqc


def run_with_harness_recovery(
    operation: Callable[[], dict[str, Any]],
    *,
    max_retries: int,
    delay_seconds: float = 2.0,
    on_retry: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Rebuild a failed job directory after transient harness exceptions."""
    errors: list[str] = []
    for recovery_number in range(max_retries + 1):
        try:
            result = operation()
        except Exception as exc:
            errors.append(repr(exc))
            if recovery_number >= max_retries:
                return {
                    "status": "harness-error",
                    "error": errors[-1],
                    "harness_retries": recovery_number,
                    "harness_errors": errors,
                }
            if on_retry is not None:
                on_retry(recovery_number + 1, errors[-1])
            if delay_seconds:
                time.sleep(delay_seconds * (2 ** recovery_number))
            continue
        if errors:
            result = dict(result)
            result["harness_retries"] = len(errors)
            result["harness_errors"] = errors
        return result
    raise AssertionError("unreachable")


def run_job(
    ledger: RunLedger,
    campaign: str,
    sample_id: str,
    model: str,
    effort: str,
    timeout: int,
    executable: str,
    max_attempts: int,
    adaptive_session: AdaptiveSession | None = None,
    supervisor_model: str | None = None,
    job_time_budget: int = 7200,
    stagnation_limit: int = 2,
    min_coverage: float = 80.0,
    vlm_model: str = "gpt-5.5",
    vlm_confidence: float = 0.85,
    enable_vlm: bool = True,
) -> dict[str, Any]:
    sample_dir = EVAL_ROOT / "samples" / sample_id
    if not sample_dir.is_dir():
        raise FileNotFoundError(sample_dir)
    campaign_dir = EVAL_ROOT / "batch" / campaign
    job_dir, retry_number = allocate_job_dir(campaign_dir, sample_id, model)
    retry_suffix = f"-retry-{retry_number:03d}" if retry_number else ""
    run_id = f"{campaign}-{slug(model)}-{effort}{retry_suffix}"
    images = prepare_job(sample_dir, job_dir)
    canonical_candidate = job_dir / "candidate.dwg"
    metrics_path = job_dir / "metrics.json"
    run_dir = ledger.start(
        sample_id,
        run_id=run_id,
        agent={"system": "codex-cli", "agent_id": "cad-batch", "model": model, "reasoning_effort": effort},
        source_paths=SOURCE_PATHS,
        input_paths=sample_inputs(sample_dir),
    )
    attempts: list[dict[str, Any]] = []
    previous_candidate: Path | None = None
    previous_verdict: Path | None = None
    previous_diagnostic: Path | None = None
    pending_action = "fresh_modeling"
    job_started = time.perf_counter()
    unchanged_scores = 0
    last_score: float | None = None
    adaptive_decisions = 0
    final_result: dict[str, Any] = {"status": "failed", "score": 0.0, "coverage": 0.0}
    final_eqc: dict[str, Any] = evidence_qualified_completion({})
    best_result: dict[str, Any] | None = None
    best_eqc = -1.0
    best_eqc_result: dict[str, Any] | None = None
    best_attempt_id: str | None = None
    best_verdict_path: Path | None = None
    best_scene_path: Path | None = None
    best_diagnostic_path: Path | None = None

    for attempt_number in range(1, max_attempts + 1):
        verifier_only = pending_action == "retry_verifier"
        fresh_retry = pending_action in {"fresh_modeling", "retry_tool", "restart_mcp"}
        label = (
            "verifier-retry" if verifier_only
            else "fresh-modeling" if attempt_number == 1 or fresh_retry
            else "verifier-guided-repair"
        )
        attempt_id = ledger.add_attempt(
            run_dir,
            label=label,
            summary=(
                "Retry verifier against the unchanged candidate"
                if verifier_only
                else "Isolated Codex AutoCAD modeling job"
                if attempt_number == 1 or fresh_retry
                else "Agent-selected drawing repair from structured diagnostics"
            ),
        )
        attempt_dir = job_dir / "attempts" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        candidate = canonical_candidate if attempt_number == 1 else job_dir / f"candidate.{attempt_id}.dwg"
        events_path = attempt_dir / "codex-events.jsonl"
        stderr_path = attempt_dir / "codex-stderr.log"
        final_path = attempt_dir / "codex-final.txt"
        audit_path = attempt_dir / "mcp-audit.jsonl"
        reflection_path = attempt_dir / "reflection.json"
        diagnostic_path = attempt_dir / "diagnostic.json"
        action_path = attempt_dir / "supervisor-action.json"
        scene_path = attempt_dir / "scene.json"
        verdict_path = attempt_dir / "verdict.json"
        if verifier_only:
            assert previous_candidate is not None
            candidate = previous_candidate
            prompt = None
        elif attempt_number == 1 or previous_candidate is None or fresh_retry:
            prompt = prompt_for(sample_id, run_id, attempt_id, candidate)
        else:
            assert previous_candidate is not None and previous_verdict is not None
            prompt = repair_prompt_for(
                sample_id, run_id, attempt_id, previous_candidate,
                previous_verdict, candidate, reflection_path, previous_diagnostic,
            )
        command = None if verifier_only else codex_command(
            executable, model, effort, job_dir, images, audit_path, final_path, prompt,
        )
        started = time.perf_counter()
        return_code = None
        timed_out = False
        interrupted = False
        verifier_failed = False
        verifier_error = None
        verifier_return_code = None
        try:
            if verifier_only:
                return_code = 0
            else:
                assert command is not None
                with events_path.open("w", encoding="utf-8", newline="\n") as events_stream, stderr_path.open(
                    "w", encoding="utf-8", newline="\n",
                ) as stderr_stream:
                    completed = subprocess.run(
                        command,
                        cwd=job_dir,
                        stdin=subprocess.DEVNULL,
                        stdout=events_stream,
                        stderr=stderr_stream,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout,
                        check=False,
                    )
                return_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            with stderr_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\nTimed out after {timeout} seconds\n")
        except KeyboardInterrupt:
            interrupted = True
            with stderr_path.open("a", encoding="utf-8") as stream:
                stream.write("\nInterrupted by operator\n")
        elapsed = round(time.perf_counter() - started, 3)
        attempt_metrics = {
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "kind": label,
            "elapsed_seconds": elapsed,
            "return_code": return_code,
            "timed_out": timed_out,
            "interrupted": interrupted,
            **read_events(events_path),
        }
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
        if candidate.is_file():
            ledger.add_artifact(run_dir, attempt_id, candidate, role="candidate")
            verifier = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--sample-dir", str(sample_dir),
                    "--candidate-dwg", str(candidate),
                    "--core-console",
                    "--write-scene", str(scene_path),
                    "--output", str(verdict_path),
                ],
                cwd=EVAL_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                check=False,
            )
            verifier_return_code = verifier.returncode
            (attempt_dir / "verifier-stdout.log").write_text(verifier.stdout, encoding="utf-8")
            (attempt_dir / "verifier-stderr.log").write_text(verifier.stderr, encoding="utf-8")
            for path, role in (
                (scene_path, "scene"),
                (attempt_dir / "verifier-stdout.log", "verifier-log"),
                (attempt_dir / "verifier-stderr.log", "verifier-log"),
            ):
                if path.is_file():
                    ledger.add_artifact(run_dir, attempt_id, path, role=role)
            if verifier.returncode != 0 or not verdict_path.is_file():
                verifier_failed = True
                verifier_error = f"Verifier failed with exit code {verifier.returncode}"
                failed_verdict(
                    verdict_path, verifier_error,
                    error_type="verifier-infrastructure",
                )
        else:
            failed_verdict(verdict_path, "Codex agent did not create a repaired candidate DWG")
        attempt_metrics["verifier_failed"] = verifier_failed
        if verifier_error:
            attempt_metrics["verifier_error"] = verifier_error
        verdict_value = json.loads(verdict_path.read_text(encoding="utf-8"))
        visual_value = None
        visual_path = attempt_dir / "visual-verdict.json"
        candidate_render = attempt_dir / "candidate-render.png"
        visual_verifier_failed = False
        unverified_rubrics = [
            item for item in verdict_value.get("rubrics", [])
            if item.get("status") == "unverified"
        ]
        if enable_vlm and unverified_rubrics:
            try:
                try:
                    render_dwg_core(candidate, candidate_render)
                except Exception:
                    scene_value = json.loads(scene_path.read_text(encoding="utf-8"))
                    render_scene(scene_value, candidate_render)
                visual_value = evaluate_visual_gaps(
                    sample_dir=sample_dir,
                    deterministic_path=verdict_path,
                    candidate_images=[candidate_render],
                    reference_images=images,
                    output=visual_path,
                    work_dir=attempt_dir / "vlm-work",
                    model=vlm_model,
                    confidence_threshold=vlm_confidence,
                )
                ledger.add_artifact(run_dir, attempt_id, candidate_render, role="candidate-render")
                ledger.add_artifact(run_dir, attempt_id, visual_path, role="vlm-verdict")
                attempt_metrics["vlm_usage"] = visual_value["provider"].get("usage", {})
                for key in ("events_path", "stderr_path", "result_path"):
                    provider_path = Path(visual_value["provider"][key])
                    if provider_path.is_file():
                        ledger.add_artifact(run_dir, attempt_id, provider_path, role="vlm-log")
                ledger.event(
                    run_dir,
                    "vlm.completed",
                    f"Visual evaluator decision: {visual_value['combined']['decision']}",
                    status=visual_value["combined"]["decision"],
                    actor="vlm-verifier",
                    attempt_id=attempt_id,
                    payload={
                        "model": vlm_model,
                        "coverage_before": visual_value["combined"]["coverage_before"],
                        "coverage_after": visual_value["combined"]["coverage_after"],
                    },
                )
            except Exception as exc:
                visual_verifier_failed = True
                visual_error_path = attempt_dir / "vlm-error.log"
                visual_error_path.write_text(traceback.format_exc(), encoding="utf-8")
                attempt_metrics["vlm_error"] = repr(exc)
                attempt_metrics["errors"].append(f"Visual verifier failed: {exc!r}")
                ledger.add_artifact(run_dir, attempt_id, visual_error_path, role="vlm-error")
        final_eqc = evidence_qualified_completion(verdict_value, visual_value)
        if visual_value is not None:
            verdict_value["visual_evidence"] = visual_value
        verdict_value["eqc"] = final_eqc
        verdict_path.write_text(
            json.dumps(verdict_value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        attempt_metrics["eqc"] = final_eqc
        attempt_metrics["visual_verifier_failed"] = visual_verifier_failed
        verdict_coverage = float(verdict_value.get("coverage", 0.0) or 0.0)
        coverage_gap = (
            adaptive_session is not None
            and below_minimum_coverage(verdict_value, min_coverage)
        )
        if verifier_failed:
            outcome = "infrastructure_error"
            component = "verifier"
            summary = verifier_error or "Verifier infrastructure failure"
            diagnostic_stderr = attempt_dir / "verifier-stderr.log"
            diagnostic_stdout = attempt_dir / "verifier-stdout.log"
        elif visual_verifier_failed and verdict_value.get("passed"):
            outcome = "infrastructure_error"
            component = "verifier"
            summary = "Visual verifier could not resolve deterministic evidence gaps"
            diagnostic_stderr = attempt_dir / "vlm-error.log"
            diagnostic_stdout = attempt_dir / "verifier-stdout.log"
        elif not candidate.is_file() or (return_code not in (None, 0)) or timed_out:
            outcome = "agent_error"
            component = "harness"
            summary = "Modeling agent did not produce a verifiable candidate"
            diagnostic_stderr = stderr_path
            diagnostic_stdout = events_path
        elif coverage_gap:
            outcome = "coverage_gap"
            component = "verifier"
            summary = (
                f"Verifier passed but covered only {verdict_coverage:.2f}% of checks; "
                f"adaptive minimum is {min_coverage:.2f}%"
            )
            diagnostic_stderr = attempt_dir / "verifier-stderr.log"
            diagnostic_stdout = attempt_dir / "verifier-stdout.log"
        elif final_eqc.get("success"):
            outcome = "success"
            component = "drawing"
            summary = "Candidate passed evidence-qualified verification"
            diagnostic_stderr = attempt_dir / "verifier-stderr.log"
            diagnostic_stdout = attempt_dir / "verifier-stdout.log"
        else:
            outcome = "evaluation_failure"
            component = "drawing"
            summary = "Candidate did not satisfy all verifier checks"
            diagnostic_stderr = attempt_dir / "verifier-stderr.log"
            diagnostic_stdout = attempt_dir / "verifier-stdout.log"
        diagnostic = build_diagnostic(
            sample_id=sample_id, run_id=run_id, attempt_id=attempt_id,
            stage="verification" if candidate.is_file() else "modeling",
            component=component, outcome=outcome, summary=summary,
            retryable=outcome != "success",
            return_code=verifier_return_code if candidate.is_file() else return_code,
            timed_out=timed_out, verdict=verdict_value,
            stderr_path=diagnostic_stderr, stdout_path=diagnostic_stdout,
            artifacts=((candidate if candidate.is_file() else None, "candidate"),
                       (scene_path if scene_path.is_file() else None, "scene"),
                       (verdict_path, "verdict")),
            tool_errors=attempt_metrics.get("errors", []),
        )
        diagnostic_path.write_text(
            json.dumps(diagnostic, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        ledger.add_artifact(run_dir, attempt_id, diagnostic_path, role="diagnostic")
        final_result = ledger.finish(run_dir, attempt_id, verdict_path)
        attempt_metrics["agent_elapsed_seconds"] = attempt_metrics["elapsed_seconds"]
        attempt_metrics["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        attempt_metrics["verification_elapsed_seconds"] = round(
            attempt_metrics["elapsed_seconds"] - attempt_metrics["agent_elapsed_seconds"], 3,
        )
        attempt_metrics.update(final_result)
        attempts.append(attempt_metrics)
        attempt_eqc = float(final_eqc.get("eqc", 0.0) or 0.0)
        if should_select_checkpoint(candidate, attempt_eqc, best_eqc):
            if candidate != canonical_candidate:
                shutil.copy2(candidate, canonical_candidate)
            best_eqc = attempt_eqc
            best_eqc_result = dict(final_eqc)
            best_result = dict(final_result)
            best_attempt_id = attempt_id
            best_verdict_path = verdict_path
            best_scene_path = scene_path if scene_path.is_file() else None
            best_diagnostic_path = diagnostic_path
            shutil.copy2(verdict_path, job_dir / "verdict.json")
            if best_scene_path is not None:
                shutil.copy2(best_scene_path, job_dir / "scene.json")
        previous_candidate = canonical_candidate if best_result is not None else None
        previous_verdict = best_verdict_path
        previous_diagnostic = best_diagnostic_path
        score = attempt_eqc
        unchanged_scores = unchanged_scores + 1 if last_score is not None and score <= last_score else 0
        last_score = max(last_score or score, score)
        pending_action = "repair_drawing"
        if visual_verifier_failed and verdict_value.get("passed"):
            pending_action = "retry_verifier"
        if (
            adaptive_session is not None
            and (final_result.get("status") != "passed" or coverage_gap)
            and not interrupted
        ):
            decision_diagnostic = diagnostic
            while adaptive_decisions < max_attempts:
                adaptive_decisions += 1
                action = adaptive_session.decide(
                    decision_diagnostic, model=supervisor_model or model,
                    effort=effort, executable=executable,
                )
                step_suffix = f"s{adaptive_decisions:03d}"
                step_action_path = action_path.with_name(f"supervisor-action.{step_suffix}.json")
                step_action_path.write_text(
                    json.dumps(action, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                )
                ledger.add_artifact(run_dir, attempt_id, step_action_path, role="supervisor-action")
                name = action["action"]
                if not (name.startswith("patch_") or name == "add_test"):
                    pending_action = name
                    break
                try:
                    patch_result = adaptive_session.apply_patch(
                        action, decision_diagnostic, model=supervisor_model or model,
                        effort=effort, executable=executable,
                    )
                    patch_traceback = ""
                except Exception as exc:
                    patch_traceback = traceback.format_exc()
                    patch_result = {
                        "iteration": adaptive_session.manifest.get("iteration"),
                        "action": name,
                        "changed_files": [],
                        "tests": {
                            "passed": False,
                            "return_code": 1,
                            "targets": [],
                            "errors": [repr(exc)],
                        },
                        "rolled_back": True,
                    }
                patch_path = attempt_dir / f"system-patch-result.{step_suffix}.json"
                patch_path.write_text(
                    json.dumps(patch_result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                )
                ledger.add_artifact(run_dir, attempt_id, patch_path, role="system-patch")
                if patch_result.get("tests", {}).get("passed", False):
                    if name == "patch_verifier" and previous_candidate is not None:
                        pending_action = "retry_verifier"
                    else:
                        pending_action = "repair_drawing" if previous_candidate is not None else "fresh_modeling"
                    break

                patch_stderr = attempt_dir / f"system-patch-stderr.{step_suffix}.log"
                test_data = patch_result.get("tests", {})
                patch_stderr.write_text(
                    patch_traceback or str(test_data.get("stderr_tail", "")), encoding="utf-8",
                )
                patch_diagnostic_path = attempt_dir / f"system-patch-diagnostic.{step_suffix}.json"
                decision_diagnostic = build_diagnostic(
                    sample_id=sample_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    stage="system_patch_validation",
                    component=action.get("component") or "harness",
                    outcome="infrastructure_error",
                    summary="Candidate system patch was rejected and rolled back",
                    retryable=True,
                    return_code=test_data.get("return_code"),
                    verdict={"passed": False, "patch_result": patch_result},
                    stderr_path=patch_stderr,
                    artifacts=((patch_path, "system-patch"),),
                    tool_errors=test_data.get("errors", []),
                )
                patch_diagnostic_path.write_text(
                    json.dumps(decision_diagnostic, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                ledger.add_artifact(
                    run_dir, attempt_id, patch_diagnostic_path, role="system-patch-diagnostic",
                )
            else:
                pending_action = "stop"
        if (
            (final_result.get("status") == "passed" and not coverage_gap)
            or interrupted
            or pending_action == "stop"
            or time.perf_counter() - job_started >= job_time_budget
            or unchanged_scores >= stagnation_limit
            or (adaptive_session is None and (previous_candidate is None or verifier_failed))
        ):
            break

    if best_result is not None:
        assert best_attempt_id is not None and best_verdict_path is not None
        final_result = ledger.select_attempt(run_dir, best_attempt_id)
        final_eqc = best_eqc_result or final_eqc
        shutil.copy2(best_verdict_path, job_dir / "verdict.json")
        if best_scene_path is not None:
            shutil.copy2(best_scene_path, job_dir / "scene.json")

    usage_keys = (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens",
    )
    metrics = {
        "campaign": campaign,
        "sample_id": sample_id,
        "run_id": run_id,
        "model": model,
        "reasoning_effort": effort,
        "elapsed_seconds": round(sum(item["elapsed_seconds"] for item in attempts), 3),
        "return_code": attempts[-1]["return_code"] if attempts else None,
        "timed_out": any(item["timed_out"] for item in attempts),
        "interrupted": any(item["interrupted"] for item in attempts),
        "execution_backend": "core_console",
        "thread_id": attempts[-1].get("thread_id") if attempts else None,
        "usage": {
            key: sum(int(item.get("usage", {}).get(key, 0) or 0) for item in attempts)
            for key in usage_keys
        },
        "vlm_usage": {
            key: sum(int(item.get("vlm_usage", {}).get(key, 0) or 0) for item in attempts)
            for key in usage_keys
        },
        "errors": [error for item in attempts for error in item.get("errors", [])],
        "attempts": attempts,
        "eqc": final_eqc,
        "selected_attempt_id": best_attempt_id,
    }
    metrics["total_usage"] = {
        key: metrics["usage"][key] + metrics["vlm_usage"][key]
        for key in usage_keys
    }
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if attempts:
        ledger.add_artifact(run_dir, attempts[-1]["attempt_id"], metrics_path, role="metrics")
    integrity = ledger.verify_integrity(run_dir)
    result = {**metrics, **final_result, "integrity": integrity, "job_dir": str(job_dir)}
    if best_result is None and attempts and attempts[-1].get("verifier_failed"):
        result.update({
            "status": "harness-error",
            "error": "Verifier infrastructure failure; drawing score is invalid",
        })
    elif (
        best_result is None
        and attempts
        and attempts[-1].get("visual_verifier_failed")
        and result.get("legacy_status") == "passed"
    ):
        result.update({
            "status": "evaluation-incomplete",
            "error": "Visual verifier failed after automatic retries; EQC is incomplete",
        })
    elif (
        adaptive_session is not None
        and result.get("status") == "passed"
        and float(result.get("coverage", 0.0) or 0.0) < min_coverage
    ):
        result.update({
            "status": "coverage-insufficient",
            "error": (
                f"Verifier coverage {float(result.get('coverage', 0.0) or 0.0):.2f}% "
                f"is below adaptive minimum {min_coverage:.2f}%"
            ),
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default=f"smoke-{utc_stamp()}")
    parser.add_argument("--model", action="append", dest="models")
    sample_group = parser.add_mutually_exclusive_group()
    sample_group.add_argument("--sample", action="append", dest="samples")
    sample_group.add_argument(
        "--all-samples", action="store_true",
        help="Run every sample directory in stable identifier order",
    )
    parser.add_argument("--reasoning-effort", default="medium", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument(
        "--protocol-mode", choices=("development", "pilot", "frozen-evaluation"),
        help="Evaluation protocol boundary; adaptive sessions require development mode",
    )
    parser.add_argument(
        "--split-manifest", type=Path,
        help="Split JSON to bind; frozen evaluation requires an explicit sealed paper-final split",
    )
    parser.add_argument("--vlm-model", default="gpt-5.5")
    parser.add_argument("--vlm-confidence", type=float, default=0.85)
    parser.add_argument("--disable-vlm", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--proposal", help="Evaluate isolated candidate sources from an improvement proposal")
    parser.add_argument("--adaptive-session", help="Run a development-only online self-improvement session")
    parser.add_argument("--supervisor-model", help="Model used for adaptive decisions; defaults to the drawing model")
    parser.add_argument(
        "--max-attempts", type=int, default=3,
        help="Maximum fresh-modeling plus verifier-guided repair attempts per job",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--job-time-budget", type=int, default=7200)
    parser.add_argument("--stagnation-limit", type=int, default=2)
    parser.add_argument(
        "--max-harness-retries", type=int, default=2,
        help="Automatic fresh-job retries after transient harness exceptions",
    )
    parser.add_argument(
        "--min-coverage", type=float, default=80.0,
        help="Minimum verifier coverage accepted as success in adaptive mode",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=8,
        help="Adaptive decision/action iteration budget; separate from fixed-run repair attempts",
    )
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    if args.max_iterations < 1:
        parser.error("--max-iterations must be at least 1")
    if args.max_jobs is not None and args.max_jobs < 1:
        parser.error("--max-jobs must be at least 1")
    if args.max_harness_retries < 0:
        parser.error("--max-harness-retries cannot be negative")
    if not 0.0 <= args.min_coverage <= 100.0:
        parser.error("--min-coverage must be between 0 and 100")
    if not 0.0 <= args.vlm_confidence <= 1.0:
        parser.error("--vlm-confidence must be between 0 and 1")
    models = args.models or list(DEFAULT_MODELS)
    samples = (
        sorted(path.name for path in (EVAL_ROOT / "samples").iterdir() if path.is_dir())
        if args.all_samples
        else args.samples or list(DEFAULT_SMOKE_SAMPLES)
    )
    profile = {"type": "production"}
    adaptive_session = None
    if args.proposal and args.adaptive_session:
        parser.error("--proposal and --adaptive-session are mutually exclusive")
    if args.proposal:
        proposal = activate_proposal(args.proposal)
        profile = {"type": "proposal", "proposal_id": proposal["proposal_id"]}
    elif args.adaptive_session:
        adaptive_session = AdaptiveSession(EVAL_ROOT, args.adaptive_session, create=True)
        development = set(json.loads(
            (EVAL_ROOT / "improvement/split.json").read_text(encoding="utf-8")
        )["development"])
        holdout = sorted(set(samples) - development)
        if holdout:
            parser.error(f"Adaptive modification is development-only; non-development samples: {holdout}")
        activate_adaptive_session(adaptive_session)
        profile = {"type": "adaptive", "session_id": args.adaptive_session}
    protocol_mode = args.protocol_mode or (
        "development" if adaptive_session is not None else "pilot"
    )
    if adaptive_session is not None and protocol_mode != "development":
        parser.error("Adaptive modification requires --protocol-mode development")
    executable = shutil.which("codex")
    if not executable:
        raise FileNotFoundError("codex executable was not found")
    jobs = [(sample, model) for sample in samples for model in models]
    if args.max_jobs is not None:
        jobs = jobs[:args.max_jobs]
    scheduled_samples = list(dict.fromkeys(sample for sample, _ in jobs))
    scheduled_models = list(dict.fromkeys(model for _, model in jobs))
    campaign_dir = EVAL_ROOT / "batch" / args.campaign
    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / "campaign-manifest.json"
    existing_created_at = None
    if manifest_path.is_file():
        existing_created_at = json.loads(
            manifest_path.read_text(encoding="utf-8")
        ).get("created_at")
    campaign_manifest = build_campaign_manifest(
        campaign_id=args.campaign,
        mode=protocol_mode,
        eval_root=EVAL_ROOT,
        sample_ids=scheduled_samples,
        models=[
            {"name": model, "reasoning_effort": args.reasoning_effort}
            for model in scheduled_models
        ],
        source_paths=SOURCE_PATHS,
        execution={
            "timeout_seconds": args.timeout,
            "max_attempts": args.max_attempts,
            "max_iterations": args.max_iterations if adaptive_session else None,
            "job_time_budget_seconds": args.job_time_budget,
            "stagnation_limit": args.stagnation_limit,
            "max_harness_retries": args.max_harness_retries,
            "minimum_coverage": args.min_coverage if adaptive_session else None,
            "vlm": {
                "enabled": not args.disable_vlm,
                "model": args.vlm_model,
                "confidence_threshold": args.vlm_confidence,
            },
            "system_profile": profile,
            "jobs": [
                {"sample_id": sample, "model": model} for sample, model in jobs
            ],
        },
        split_path=args.split_manifest,
        created_at=existing_created_at,
    )
    write_immutable_manifest(manifest_path, campaign_manifest)
    plan = {
        "campaign": args.campaign,
        "models": models,
        "samples": samples,
        "reasoning_effort": args.reasoning_effort,
        "max_attempts": args.max_attempts,
        "max_iterations": args.max_iterations if adaptive_session else None,
        "min_coverage": args.min_coverage if adaptive_session else None,
        "system_profile": profile,
        "protocol_mode": protocol_mode,
        "manifest_sha256": campaign_manifest["manifest_sha256"],
        "jobs": [{"sample_id": sample, "model": model} for sample, model in jobs],
    }
    (campaign_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False))
    if args.dry_run:
        return
    ledger = RunLedger(EVAL_ROOT)
    results_path = campaign_dir / "results.json"
    results = load_resumable_results(results_path)
    completed_jobs = {
        (item.get("sample_id"), item.get("model"))
        for item in results if is_terminal_result(item)
    }
    for sample, model in jobs:
        if (sample, model) in completed_jobs:
            print(json.dumps({"sample_id": sample, "model": model, "status": "skipped-existing"}))
            continue
        def execute_job() -> dict[str, Any]:
            return run_job(
                ledger, args.campaign, sample, model, args.reasoning_effort,
                args.timeout, executable,
                args.max_iterations if adaptive_session else args.max_attempts,
                adaptive_session=adaptive_session,
                supervisor_model=args.supervisor_model,
                job_time_budget=args.job_time_budget,
                stagnation_limit=args.stagnation_limit,
                min_coverage=args.min_coverage,
                vlm_model=args.vlm_model,
                vlm_confidence=args.vlm_confidence,
                enable_vlm=not args.disable_vlm,
            )

        def report_retry(recovery_number: int, error: str) -> None:
            print(json.dumps({
                "sample_id": sample,
                "model": model,
                "status": "harness-retrying",
                "recovery_number": recovery_number,
                "error": error,
            }, ensure_ascii=False))

        result = run_with_harness_recovery(
            execute_job,
            max_retries=args.max_harness_retries,
            on_retry=report_retry,
        )
        result.setdefault("sample_id", sample)
        result.setdefault("model", model)
        results.append(result)
        results_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        if result.get("interrupted") or result.get("status") == "harness-error":
            reason = (
                "Job was interrupted" if result.get("interrupted")
                else "Infrastructure failure requires operator or automatic recovery"
            )
            print(json.dumps({"status": "campaign-stopped", "reason": reason}))
            break


if __name__ == "__main__":
    main()
