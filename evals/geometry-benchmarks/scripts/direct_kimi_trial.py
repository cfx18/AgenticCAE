"""Run one native Kimi Code conversation, followed by held-out geometry evaluation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from cad_evoloop.evaluation.geometry_campaign import (
    _safe_manifest_path,
    _source_paths,
    failed_geometry_verdict,
    geometry_verdict,
    load_geometry_manifest,
    slug,
    stage_agent_inputs,
)
from cad_evoloop.evaluation.geometry_score import PROTOCOL_ID, score_geometry_files
from cad_evoloop.ledger import RunLedger
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root
from cad_evoloop.verification.export_core_console import export_dwg_core

PAPER_KIMI_SCRIPT = project_root() / "evals/Paper_filmcooling/scripts/run_paper_kimi.py"
sys.path.insert(0, str(PAPER_KIMI_SCRIPT.parent))
from run_paper_kimi import (  # noqa: E402
    discover_deliverable_dwgs,
    extract_final_text,
    find_autocad_python,
    find_kimi_invocation,
    parse_dotenv,
    safe_endpoint_label,
    validate_kimi_env,
    write_mcp_config,
)


def direct_prompt(workspace: Path, job_dir: Path, sample_id: str, run_id: str, candidate: Path) -> str:
    return f"""Reconstruct the part specified by task.json and the engineering drawing images in input_files.
Use only task.json and input_files as design evidence. Do not read parent directories,
dataset manifests, ground-truth geometry, previous runs, evaluation records, or external
solutions. Keep all new files inside the current task directory: {job_dir.as_posix()}.
You may read the AutoCAD skill at {workspace.as_posix()}/.agents/skills/autocad-image-modeling/SKILL.md.

Use the configured AutoCAD MCP tools for CAD work. Set run context to sample_id
{sample_id}, run_id {run_id}, attempt_id a001. Use isolated autocad_core_start and
autocad_core_status, not the desktop AutoCAD session. These tools accept unrestricted
AutoLISP/AutoCAD commands. Core Console has no desktop ActiveX document object; use
native commands and entity functions. Every Core Console job must have different
input and output paths. Preserve recoverable intermediate DWGs in this directory.

The required output is one native editable AutoCAD 3DSOLID in model space, matching
the visible dimensions and features. Do not add drawing views, text, or dimensions.
Decide for yourself how to inspect the drawing, plan, construct, check, and revise
the model. You may use your normal tools to inspect source images and your own
outputs. There is no prescribed IR, no externally scheduled repair turn, and no
ground-truth score tool. Finish when your own checks support the best reconstruction
you can make. Do not stop merely because the first construction succeeds.

Save the final submission to {candidate.as_posix()} and confirm its Core Console job
has succeeded. Briefly report the output, checks performed, and remaining uncertainty.
"""


def parse_kimi_events(events_path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    errors: list[Any] = []
    session_id = None
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    if not events_path.is_file():
        return {"thread_id": None, "usage": usage, "errors": ["events file missing"], "counts": counts}
    for raw in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append({"type": "json_decode", "error": str(exc)})
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or event.get("event") or "")
        counts[kind] = counts.get(kind, 0) + 1
        session_id = session_id or event.get("sessionId") or event.get("session_id")
        if kind in {"error", "llm.error"}:
            errors.append(event)
        item_usage = event.get("usage")
        if isinstance(item_usage, dict):
            usage["input_tokens"] += int(item_usage.get("input", item_usage.get("inputOther", 0)) or 0)
            usage["cached_input_tokens"] += int(item_usage.get("inputCacheRead", 0) or 0)
            usage["output_tokens"] += int(item_usage.get("output", 0) or 0)
    return {"thread_id": session_id, "usage": usage, "errors": errors, "counts": counts}


def run_process(
    command: list[str], cwd: Path, env: dict[str, str], stdout_path: Path,
    stderr_path: Path, timeout: int,
) -> tuple[int, bool]:
    with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
            return process.returncode if process.returncode is not None else -9, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default="omnimech:2")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--env-file", type=Path, default=project_root() / "evals/Paper_filmcooling/kimi/.env")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--autocad-python", type=Path)
    args = parser.parse_args()

    root = project_root().resolve()
    if slug(args.campaign) != args.campaign or args.timeout < 1:
        parser.error("Use a safe campaign identifier and positive timeout")
    manifest_path, manifest = load_geometry_manifest(
        root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    )
    sample = next(row for row in manifest["samples"] if row["sample_id"] == args.sample)
    kimi_values = parse_dotenv(args.env_file.resolve())
    validate_kimi_env(kimi_values)
    invocation = find_kimi_invocation(root, args.executable)
    autocad_python = find_autocad_python(args.autocad_python)
    version = subprocess.check_output(
        [*invocation, "--version"], text=True, encoding="utf-8", errors="replace"
    ).strip()

    model = kimi_values["KIMI_MODEL_NAME"]
    effort = kimi_values.get("KIMI_MODEL_THINKING_EFFORT", "")
    campaign_dir = root / "evals/geometry-benchmarks/batch" / args.campaign
    job_dir = campaign_dir / slug(args.sample) / slug(model)
    attempt_dir = job_dir / "attempts/a001"
    candidate = job_dir / "candidate.a001.dwg"
    run_id = f"{args.campaign}-{slug(model)}-{slug(effort or 'default')}"
    campaign_dir.mkdir(parents=True, exist_ok=False)
    attempt_dir.mkdir(parents=True)
    images = stage_agent_inputs(manifest_path, sample, job_dir)
    prompt = direct_prompt(root, job_dir, args.sample, run_id, candidate)
    prompt_path = attempt_dir / "action-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
    kimi_home = write_mcp_config(root, job_dir, attempt_dir, autocad_python)
    events_path = attempt_dir / "kimi-events.jsonl"
    stderr_path = attempt_dir / "kimi-stderr.log"
    final_path = attempt_dir / "kimi-final.txt"
    command = [*invocation, "--prompt", prompt, "--output-format", "stream-json"]
    write_json_atomic(attempt_dir / "command.json", {
        "argv": command,
        "environment": {
            "KIMI_CODE_HOME": kimi_home.relative_to(job_dir).as_posix(),
            "KIMI_MODEL_API_KEY": "[REDACTED]",
            "KIMI_MODEL_BASE_URL": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "KIMI_MODEL_NAME": model,
            "KIMI_MODEL_THINKING_EFFORT": effort,
        },
    })
    write_json_atomic(campaign_dir / "trial-config.json", {
        "schema_version": "1.0", "state": "running", "created_at": utc_now(),
        "sample_id": args.sample, "model": model, "effort": effort,
        "timeout": args.timeout, "kimi_version": version,
        "api_endpoint": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
        "harness": "native-kimi-code-single-conversation",
        "external_repair_turns": 0, "gt_feedback_during_run": False,
        "forced_ir": False,
        "input_sha256": {path.name: sha256_file(path) for path in images},
    })
    child_env = os.environ.copy()
    child_env.update(kimi_values)
    child_env.update({
        "KIMI_CODE_HOME": str(kimi_home),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_SHELL_PATH": str(Path(r"C:\Program Files\Git\bin\bash.exe")),
        "KIMI_MCP_STARTUP_TIMEOUT_MS": "30000",
        "KIMI_MCP_TOOL_TIMEOUT_MS": "180000",
        "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "drain",
        "KIMI_CODE_BACKGROUND_PRINT_WAIT_CEILING_S": str(args.timeout),
    })

    ledger = RunLedger(root / "evals/geometry-benchmarks")
    run_dir = ledger.start(
        slug(args.sample), run_id=run_id,
        agent={"system": "native-kimi-code", "model": model,
               "reasoning_effort": effort, "external_sample_id": args.sample},
        source_paths=[Path(__file__).resolve(), PAPER_KIMI_SCRIPT, *_source_paths(root)],
        input_paths=[job_dir / "task.json", *images, prompt_path, attempt_dir / "command.json"],
    )
    attempt_id = ledger.add_attempt(run_dir, label="native-kimi-code-continuous-session")
    started = time.perf_counter()
    print(f"START {run_id}", flush=True)
    return_code, timed_out = run_process(
        command, job_dir, child_env, events_path, stderr_path, args.timeout
    )
    elapsed = round(time.perf_counter() - started, 3)
    final_text = extract_final_text(events_path)
    if final_text:
        final_path.write_text(final_text + "\n", encoding="utf-8", newline="\n")
    if not candidate.is_file():
        deliverables = [path for path in discover_deliverable_dwgs(job_dir) if path.name.casefold() != "candidate.dwg"]
        if deliverables:
            shutil.copy2(deliverables[-1], candidate)
    event_data = parse_kimi_events(events_path)
    ground_truth = _safe_manifest_path(manifest_path.parent, sample["ground_truth_step"])
    verdict_path = attempt_dir / "geometry-verdict.json"
    if candidate.is_file():
        shutil.copy2(candidate, job_dir / "candidate.dwg")
        try:
            mesh = export_dwg_core(candidate, attempt_dir / "candidate.stl", timeout=180)
            verdict = geometry_verdict(score_geometry_files(
                mesh, ground_truth, sample_count=20000, voxel_resolution=64,
            ), args.sample)
        except Exception as exc:
            verdict = failed_geometry_verdict(args.sample, repr(exc), "geometry-verifier-error")
    else:
        verdict = failed_geometry_verdict(args.sample, "Final DWG not produced", "agent-output-missing")
    write_json_atomic(verdict_path, verdict)
    for path in sorted(attempt_dir.iterdir()):
        if path.is_file() and path != verdict_path:
            ledger.add_artifact(run_dir, attempt_id, path, role=slug(path.stem))
    if candidate.is_file():
        ledger.add_artifact(run_dir, attempt_id, candidate, role="candidate")
    audit_path = attempt_dir / "mcp-audit.jsonl"
    if audit_path.is_file():
        ledger.ingest_mcp_audit(run_dir, audit_path)
    ledger.finish(run_dir, attempt_id, verdict_path)
    stop_reason = "time_budget" if timed_out else "agent_stop" if return_code == 0 else "provider_error"
    attempt = {
        "attempt_id": attempt_id, "attempt_number": 1, "elapsed_seconds": elapsed,
        "return_code": return_code, "timed_out": timed_out, "score": verdict["score"],
        "passed": verdict["passed"], "verdict": str(verdict_path),
        "thread_id": event_data["thread_id"], "usage": event_data["usage"],
        "errors": event_data["errors"], "event_counts": event_data["counts"],
        "agent_decision": "stop" if return_code == 0 else None,
    }
    result = {
        "schema_version": "1.0", "protocol": PROTOCOL_ID,
        "agent_loop_protocol": "native-kimi-code-single-conversation-v1",
        "campaign": args.campaign, "sample_id": args.sample, "ledger_sample_id": slug(args.sample),
        "run_id": run_id, "model": model, "reasoning_effort": effort,
        "status": "passed" if verdict["passed"] else "failed", "score": verdict["score"],
        "passed": verdict["passed"], "selected_attempt_id": attempt_id, "stop_reason": stop_reason,
        "agent_requested_continue": False, "attempts": [attempt],
        "candidate_sha256": sha256_file(candidate) if candidate.is_file() else None,
        "ground_truth_sha256": sha256_file(ground_truth), "ledger_run": str(run_dir),
        "job_dir": str(job_dir), "integrity": ledger.verify_integrity(run_dir),
    }
    write_json_atomic(job_dir / "result.json", result)
    (campaign_dir / "results.json").write_text(json.dumps([result], indent=2) + "\n", encoding="utf-8")
    write_json_atomic(campaign_dir / "campaign-manifest.json", {
        "schema_version": "1.0", "campaign_id": args.campaign,
        "agent_loop_protocol": result["agent_loop_protocol"], "protocol": PROTOCOL_ID,
        "source_manifest_sha256": sha256_file(manifest_path), "sample_ids": [args.sample],
        "models": [{"name": model, "model": model}], "reasoning_effort": effort,
    })
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
