"""One native Codex conversation, followed by held-out geometry evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from cad_evoloop.evaluation.geometry_campaign import (
    _run_codex_process,
    _safe_manifest_path,
    _source_paths,
    codex_command,
    failed_geometry_verdict,
    geometry_verdict,
    load_geometry_manifest,
    slug,
    stage_agent_inputs,
)
from cad_evoloop.agent.models.codex_cli import parse_codex_events
from cad_evoloop.evaluation.geometry_score import PROTOCOL_ID, score_geometry_files
from cad_evoloop.ledger import RunLedger
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root
from cad_evoloop.verification.export_core_console import export_dwg_core


def direct_prompt(workspace: Path, sample_id: str, run_id: str, candidate: Path) -> str:
    return f"""Reconstruct the part specified by task.json and the attached engineering drawing.
Use only task.json and input_files as design evidence. Do not read parent directories,
dataset manifests, ground-truth geometry, previous runs, evaluation records, or external
solutions. Keep all new files inside the current task directory. You may read the
AutoCAD skill at {workspace.as_posix()}/.agents/skills/autocad-image-modeling/SKILL.md.

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default="omnimech:2")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="ultra")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--transport", choices=("auto", "https"), default="auto")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute-prepared", action="store_true")
    args = parser.parse_args()
    root = project_root()
    if slug(args.campaign) != args.campaign or args.timeout < 1:
        parser.error("Use a safe campaign identifier and positive timeout")
    manifest_path, manifest = load_geometry_manifest(
        root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    )
    sample = next(row for row in manifest["samples"] if row["sample_id"] == args.sample)
    campaign_dir = root / "evals/geometry-benchmarks/batch" / args.campaign
    job_dir = campaign_dir / slug(args.sample) / slug(args.model)
    attempt_dir = job_dir / "attempts/a001"
    candidate = job_dir / "candidate.a001.dwg"
    run_id = f"{args.campaign}-{slug(args.model)}-{args.effort}"
    executable = str(args.executable or shutil.which("codex") or "")
    if not Path(executable).is_file():
        raise FileNotFoundError("Resolve an installed Codex executable before running")
    version = subprocess.check_output([executable, "--version"], text=True).strip()
    if args.execute_prepared:
        record = json.loads((campaign_dir / "trial-config.json").read_text(encoding="utf-8"))
        expected = (args.sample, args.model, args.effort, args.timeout, executable, version)
        actual = tuple(record[k] for k in ("sample_id", "model", "effort", "timeout", "executable", "version"))
        if actual != expected or record["state"] != "prepared":
            raise ValueError("Prepared configuration mismatch or trial already started")
        if record.get("transport", "auto") != args.transport:
            raise ValueError("Prepared transport configuration mismatch")
        images = sorted((job_dir / "input_files").glob("input-*"))
        for path in images:
            if sha256_file(path) != record["input_sha256"][path.name]:
                raise ValueError("Prepared input changed")
    else:
        campaign_dir.mkdir(parents=True, exist_ok=False)
        attempt_dir.mkdir(parents=True)
        images = stage_agent_inputs(manifest_path, sample, job_dir)
        record = {
            "schema_version": "1.0", "state": "prepared", "created_at": utc_now(),
            "sample_id": args.sample, "model": args.model, "effort": args.effort,
            "timeout": args.timeout, "executable": executable, "version": version,
            "transport": args.transport,
            "harness": "native-codex-single-conversation", "external_repair_turns": 0,
            "gt_feedback_during_run": False, "forced_ir": False,
            "input_sha256": {path.name: sha256_file(path) for path in images},
            "isolation": "Source-only staging and prompt restriction; not an OS read-isolation claim",
            "comparison_caveat": "Harness, effort, feedback access, CLI version and time differ from historical controls",
        }
        write_json_atomic(campaign_dir / "trial-config.json", record)
    prompt = direct_prompt(root, args.sample, run_id, candidate)
    prompt_path = attempt_dir / "action-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    audit_path = attempt_dir / "mcp-audit.jsonl"
    events_path = attempt_dir / "codex-events.jsonl"
    command = codex_command(executable, args.model, args.effort, job_dir, images,
                            prompt, audit_path, attempt_dir / "codex-final.txt")
    if args.transport == "https":
        # This uses the same signed-in account and official backend, without WS.
        command[2:2] = [
            "-c", 'model_provider="evocad_openai_https"',
            "-c", 'model_providers.evocad_openai_https={name="OpenAI HTTPS",'
            'base_url="https://chatgpt.com/backend-api/codex",wire_api="responses",'
            'requires_openai_auth=true,supports_websockets=false}',
        ]
    write_json_atomic(attempt_dir / "command.json", {"argv": command})
    if args.prepare_only:
        print(json.dumps(record, indent=2), flush=True)
        return

    record.update(state="running", started_at=utc_now())
    write_json_atomic(campaign_dir / "trial-config.json", record)
    ledger = RunLedger(root / "evals/geometry-benchmarks")
    run_dir = ledger.start(
        slug(args.sample), run_id=run_id,
        agent={"system": "native-codex", "model": args.model,
               "reasoning_effort": args.effort, "external_sample_id": args.sample},
        source_paths=[Path(__file__).resolve(), *_source_paths(root)],
        input_paths=[job_dir / "task.json", *images, prompt_path, attempt_dir / "command.json"],
    )
    attempt_id = ledger.add_attempt(run_dir, label="native-codex-continuous-session")
    started = time.perf_counter()
    print(f"START {run_id}", flush=True)
    return_code, timed_out = _run_codex_process(
        command, cwd=job_dir, events_path=events_path,
        stderr_path=attempt_dir / "codex-stderr.log", timeout=args.timeout, stdin_text=prompt,
    )
    elapsed = round(time.perf_counter() - started, 3)
    events = parse_codex_events(events_path)
    record.update(state="evaluating", model_finished_at=utc_now(),
                  return_code=return_code, timed_out=timed_out, elapsed_seconds=elapsed)
    write_json_atomic(campaign_dir / "trial-config.json", record)
    print(f"CODEX_FINISHED rc={return_code} timeout={timed_out} seconds={elapsed}", flush=True)
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
    if audit_path.is_file():
        ledger.ingest_mcp_audit(run_dir, audit_path)
    ledger.finish(run_dir, attempt_id, verdict_path)
    stop_reason = "time_budget" if timed_out else "agent_stop" if return_code == 0 else "provider_error"
    attempt = {
        "attempt_id": attempt_id, "attempt_number": 1, "elapsed_seconds": elapsed,
        "return_code": return_code, "timed_out": timed_out, "score": verdict["score"],
        "passed": verdict["passed"], "verdict": str(verdict_path),
        "thread_id": events["thread_id"], "usage": events["usage"], "errors": events["errors"],
        "agent_decision": "stop" if return_code == 0 else None,
    }
    result = {
        "schema_version": "1.0", "protocol": PROTOCOL_ID,
        "agent_loop_protocol": "native-codex-single-conversation-v1",
        "campaign": args.campaign, "sample_id": args.sample, "ledger_sample_id": slug(args.sample),
        "run_id": run_id, "model": args.model, "reasoning_effort": args.effort,
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
        "models": [{"name": args.model, "model": args.model}], "reasoning_effort": args.effort,
    })
    record.update(state="completed", completed_at=utc_now(), result=str(job_dir / "result.json"))
    write_json_atomic(campaign_dir / "trial-config.json", record)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
