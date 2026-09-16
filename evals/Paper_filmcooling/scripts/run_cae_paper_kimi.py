"""Run one autonomous paper-to-AutoCAD-and-Fluent trajectory with Kimi Code."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
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
    safe_endpoint_label,
    sha256_file,
    validate_kimi_env,
    write_json,
    write_mcp_config,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def task_prompt(root: Path, task_dir: Path, source_pdf: Path) -> str:
    return f"""Read {source_pdf.as_posix()} and reproduce the structure and simulation case
described in the paper using the local AutoCAD installation and ANSYS 2022 R1 Fluent
Meshing/Fluent.

Own the complete task: extract the paper's information, decide how to construct and verify
the geometry, transfer it to Fluent, create and check the mesh, define the physical models and
boundary conditions supported by the paper, and preserve a reproducible case. Do not invent
missing paper inputs silently; record assumptions and distinguish completed, verified work from
anything that remains underdetermined or unvalidated.

Keep every generated file and execution record inside {task_dir.as_posix()}. Preserve editable
CAD, transferable geometry, mesh, Fluent case/data when available, journals/scripts, images,
logs, an assumptions record, and a concise final report identifying the important paths and
verification results. Use the configured AutoCAD MCP for AutoCAD work. You may read the AutoCAD
skill at {root.as_posix()}/.agents/skills/autocad-image-modeling/SKILL.md. Operate the local
Fluent installation through reproducible scripts or journals and retain their transcripts.

Do not inspect previous experiment runs or external solution directories.
"""


def run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
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
        (cwd / "attempts/a001/kimi-process.json").write_text(
            json.dumps({"pid": process.pid, "started_at": utc_now()}, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
            return process.returncode if process.returncode is not None else -9, True


def discover_outputs(task_dir: Path) -> dict[str, list[str]]:
    patterns = {
        "cad": ("*.dwg", "*.sat", "*.step", "*.stp", "*.iges", "*.igs"),
        "mesh": ("*.msh", "*.msh.h5", "*.cas", "*.cas.h5"),
        "data": ("*.dat", "*.dat.h5"),
        "journals": ("*.jou", "*.wft", "*.py", "*.lsp"),
    }
    found: dict[str, list[str]] = {}
    for category, globs in patterns.items():
        paths: set[Path] = set()
        for pattern in globs:
            paths.update(task_dir.rglob(pattern))
        found[category] = sorted(
            path.relative_to(task_dir).as_posix()
            for path in paths
            if path.is_file() and "mcp/jobs" not in path.relative_to(task_dir).as_posix()
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=21600)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--autocad-python", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    root = project_root().resolve()
    source = args.source.resolve()
    env_file = args.env_file.resolve()
    if not source.is_file() or source.suffix.casefold() != ".pdf":
        raise FileNotFoundError(f"Source PDF not found: {source}")
    if not args.campaign.replace("-", "").isalnum() or args.timeout < 1:
        parser.error("Use a safe campaign identifier and a positive timeout")

    kimi_values = parse_dotenv(env_file)
    validate_kimi_env(kimi_values)
    invocation = find_kimi_invocation(root, args.executable)
    autocad_python = find_autocad_python(args.autocad_python)
    version = subprocess.check_output(
        [*invocation, "--version"], text=True, encoding="utf-8", errors="replace"
    ).strip()
    if args.validate_only:
        print(json.dumps({
            "status": "ready",
            "kimi_version": version,
            "model": kimi_values["KIMI_MODEL_NAME"],
            "reasoning_effort": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
            "endpoint": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "autocad_python": str(autocad_python),
        }, indent=2))
        return 0

    task_dir = root / "evals/Paper_filmcooling/runs" / args.campaign
    attempt_dir = task_dir / "attempts/a001"
    input_dir = task_dir / "input"
    output_dir = task_dir / "outputs"
    task_dir.mkdir(parents=True, exist_ok=False)
    attempt_dir.mkdir(parents=True)
    input_dir.mkdir()
    output_dir.mkdir()
    staged_pdf = input_dir / "source-paper.pdf"
    shutil.copy2(source, staged_pdf)

    prompt = task_prompt(root, task_dir, staged_pdf)
    (attempt_dir / "action-prompt.md").write_text(prompt, encoding="utf-8", newline="\n")
    kimi_home = write_mcp_config(root, task_dir, attempt_dir, autocad_python)
    events_path = attempt_dir / "kimi-events.jsonl"
    stderr_path = attempt_dir / "kimi-stderr.log"
    final_path = attempt_dir / "kimi-final.md"
    command = [*invocation, "--prompt", prompt, "--output-format", "stream-json"]
    write_json(attempt_dir / "command.json", {
        "argv": command,
        "environment": {
            "KIMI_CODE_HOME": kimi_home.relative_to(task_dir).as_posix(),
            "KIMI_MODEL_API_KEY": "[REDACTED]",
            "KIMI_MODEL_BASE_URL": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "KIMI_MODEL_NAME": kimi_values["KIMI_MODEL_NAME"],
            "KIMI_MODEL_THINKING_EFFORT": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
        },
    })
    run_record = {
        "schema_version": "1.0",
        "state": "running",
        "created_at": utc_now(),
        "started_at": utc_now(),
        "campaign": args.campaign,
        "source_original": source.as_posix(),
        "source_staged": staged_pdf.relative_to(task_dir).as_posix(),
        "source_sha256": sha256_file(staged_pdf),
        "model": kimi_values["KIMI_MODEL_NAME"],
        "reasoning_effort": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
        "api_endpoint": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
        "harness": "native-kimi-code-autonomous-paper-to-autocad-fluent-v1",
        "prompt_mode": "minimal-autonomous-cae",
        "kimi_version": version,
        "autocad_mcp_python": autocad_python.as_posix(),
        "timeout_seconds": args.timeout,
        "human_geometry_preprocessing": False,
        "human_geometry_specification": False,
        "previous_run_access_allowed": False,
        "autocad_mcp_audited": True,
    }
    write_json(task_dir / "run.json", run_record)

    child_env = os.environ.copy()
    child_env.update(kimi_values)
    child_env.update({
        "KIMI_CODE_HOME": str(kimi_home),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_SHELL_PATH": str(Path(r"C:\Program Files\Git\bin\bash.exe")),
        "KIMI_MCP_STARTUP_TIMEOUT_MS": "30000",
        "KIMI_MCP_TOOL_TIMEOUT_MS": "300000",
        "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "drain",
        "KIMI_CODE_BACKGROUND_PRINT_WAIT_CEILING_S": str(args.timeout),
    })

    started = time.perf_counter()
    print(f"START {args.campaign}", flush=True)
    try:
        return_code, timed_out = run_process(
            command, task_dir, child_env, events_path, stderr_path, args.timeout
        )
        elapsed = round(time.perf_counter() - started, 3)
        final_text = extract_final_text(events_path)
        if final_text:
            final_path.write_text(final_text + "\n", encoding="utf-8", newline="\n")
        outputs = discover_outputs(task_dir)
        complete = (
            return_code == 0
            and not timed_out
            and bool(final_text)
            and bool(discover_deliverable_dwgs(task_dir))
            and bool(outputs["mesh"])
        )
        result: dict[str, object] = {
            "schema_version": "1.0",
            "status": "artifacts_ready_for_human_review" if complete else "incomplete",
            "return_code": return_code,
            "timed_out": timed_out,
            "elapsed_seconds": elapsed,
            "final_message_captured": bool(final_text),
            "outputs": outputs,
            "missing_outputs": [
                label for label, present in (
                    ("editable AutoCAD DWG", bool(discover_deliverable_dwgs(task_dir))),
                    ("Fluent mesh or case", bool(outputs["mesh"])),
                ) if not present
            ],
        }
        run_record.update(
            state="completed" if complete else "incomplete",
            completed_at=utc_now(),
            elapsed_seconds=elapsed,
        )
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "status": "execution_error",
            "error": repr(exc),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        run_record.update(state="execution_error", completed_at=utc_now(), error=repr(exc))
    write_json(task_dir / "run.json", run_record)
    result["artifacts"] = file_inventory(task_dir)
    write_json(task_dir / "result.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "artifacts_ready_for_human_review" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
