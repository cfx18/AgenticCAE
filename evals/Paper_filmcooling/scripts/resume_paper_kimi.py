"""Resume an interrupted Kimi Code paper-to-AutoCAD session in the same run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from run_paper_kimi import (
    discover_deliverable_dwgs,
    extract_final_text,
    file_inventory,
    find_autocad_python,
    find_kimi_invocation,
    parse_dotenv,
    project_root,
    run_process,
    safe_endpoint_label,
    utc_now,
    validate_kimi_env,
    write_json,
)


def latest_session_id(kimi_home: Path) -> str:
    index_path = kimi_home / "session_index.jsonl"
    if not index_path.is_file():
        raise FileNotFoundError(f"Kimi session index not found: {index_path}")
    records = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    if not records or not isinstance(records[-1].get("sessionId"), str):
        raise RuntimeError("No resumable Kimi session was found")
    return records[-1]["sessionId"]


def next_resume_number(attempt_dir: Path) -> int:
    numbers = []
    for path in attempt_dir.glob("kimi-resume-*-events.jsonl"):
        try:
            numbers.append(int(path.name.split("-")[2]))
        except (IndexError, ValueError):
            continue
    return max(numbers, default=0) + 1


def continuation_prompt(task_dir: Path) -> str:
    return f"""Continue the interrupted paper-to-AutoCAD task from the current session state.

The previous harness process stopped after queuing an AutoCAD Core Console job. Its in-memory
MCP job status no longer exists, so inspect the latest job directory and logs under
{(task_dir / 'mcp/jobs').as_posix()} instead of polling the old job ID. Diagnose the recorded
failure, continue revising the model, complete your own verification, save the final editable
AutoCAD model outside the MCP jobs directory, and provide the final response. Do not restart
the paper analysis or inspect other experiments.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--autocad-python", type=Path)
    args = parser.parse_args()
    if not args.campaign.replace("-", "").isalnum() or args.timeout < 1:
        parser.error("Use a safe campaign identifier and a positive timeout")

    root = project_root().resolve()
    task_dir = root / "evals/Paper_filmcooling/runs" / args.campaign
    attempt_dir = task_dir / "attempts/a001"
    kimi_home = attempt_dir / "kimi-home"
    if not task_dir.is_dir():
        raise FileNotFoundError(f"Run not found: {task_dir}")

    kimi_values = parse_dotenv(args.env_file.resolve())
    validate_kimi_env(kimi_values)
    invocation = find_kimi_invocation(root, args.executable)
    autocad_python = find_autocad_python(args.autocad_python)
    session_id = latest_session_id(kimi_home)
    resume_number = next_resume_number(attempt_dir)
    prefix = f"kimi-resume-{resume_number:03d}"
    prompt = continuation_prompt(task_dir)
    events_path = attempt_dir / f"{prefix}-events.jsonl"
    stderr_path = attempt_dir / f"{prefix}-stderr.log"
    command = [
        *invocation,
        "--session", session_id,
        "--prompt", prompt,
        "--output-format", "stream-json",
    ]
    write_json(attempt_dir / f"command-resume-{resume_number:03d}.json", {
        "argv": command,
        "environment": {
            "KIMI_CODE_HOME": kimi_home.relative_to(task_dir).as_posix(),
            "KIMI_MODEL_API_KEY": "[REDACTED]",
            "KIMI_MODEL_BASE_URL": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "KIMI_MODEL_NAME": kimi_values["KIMI_MODEL_NAME"],
            "KIMI_MODEL_THINKING_EFFORT": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
        },
    })

    run_path = task_dir / "run.json"
    run_record = json.loads(run_path.read_text(encoding="utf-8"))
    resumptions = run_record.setdefault("resumptions", [])
    resumptions.append({
        "number": resume_number,
        "session_id": session_id,
        "started_at": utc_now(),
        "reason": "outer harness process interrupted while AutoCAD repair loop was active",
    })
    run_record["state"] = "running"
    write_json(run_path, run_record)

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

    started = time.perf_counter()
    print(f"RESUME {args.campaign} session={session_id}", flush=True)
    try:
        return_code, timed_out = run_process(
            command, task_dir, child_env, events_path, stderr_path, args.timeout
        )
        elapsed = round(time.perf_counter() - started, 3)
        final_text = extract_final_text(events_path)
        if final_text:
            (attempt_dir / "kimi-final.md").write_text(
                final_text + "\n", encoding="utf-8", newline="\n"
            )
        discovered_dwgs = discover_deliverable_dwgs(task_dir)
        complete = return_code == 0 and not timed_out and bool(final_text) and bool(discovered_dwgs)
        result: dict[str, object] = {
            "schema_version": "1.0",
            "status": "artifacts_ready_for_human_review" if complete else "incomplete",
            "return_code": return_code,
            "timed_out": timed_out,
            "elapsed_seconds_this_resume": elapsed,
            "resume_number": resume_number,
            "session_id": session_id,
            "final_message_captured": bool(final_text),
            "discovered_dwgs": [path.relative_to(task_dir).as_posix() for path in discovered_dwgs],
            "missing_outputs": [] if discovered_dwgs else ["agent-selected final editable DWG"],
        }
        run_record.update(
            state="completed" if complete else "incomplete",
            completed_at=utc_now(),
        )
        resumptions[-1].update(
            completed_at=utc_now(), return_code=return_code, timed_out=timed_out,
            elapsed_seconds=elapsed,
        )
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "status": "execution_error",
            "error": repr(exc),
            "resume_number": resume_number,
            "elapsed_seconds_this_resume": round(time.perf_counter() - started, 3),
        }
        run_record.update(state="execution_error", completed_at=utc_now(), error=repr(exc))
    write_json(run_path, run_record)
    result["artifacts"] = file_inventory(task_dir)
    write_json(task_dir / "result.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "artifacts_ready_for_human_review" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
