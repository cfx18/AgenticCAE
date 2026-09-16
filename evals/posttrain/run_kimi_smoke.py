"""Native Kimi Code perception smoke, restricted to a public-only MCP surface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals/Paper_filmcooling/scripts"))

from run_paper_kimi import find_kimi_invocation, parse_dotenv, validate_kimi_env
from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from cad_evoloop.posttrain.environment import Episode
from cad_evoloop.posttrain.verifier import grade_episode


PROFILE = """---
name: perception-smoke
description: Inspect public CAD drawing questions and submit an answer.
tools: [mcp__pilot__observe, mcp__pilot__conclude, mcp__pilot__submit]
subagents: []
---
You are solving a CAD drawing perception task. Use only the supplied public inputs.
Use observe to inspect images, optionally crop them, and conclude to record brief
evidence-based findings. Submit your final answer with submit using the requested
JSON fields. Do not guess unavailable dimensions. There is no correctness feedback.
The task is about the drawing, not about modifying the environment.
"""

BOXED_PROFILE = """---
name: boxed-drawing-answer
description: Answer the boxed drawing question.
tools: [mcp__pilot__observe, mcp__pilot__conclude, mcp__pilot__submit]
subagents: []
---
Use observe to view the supplied image. Answer the question directly.
Return {"answer": ...} through submit. No explanation is required.
"""


def run_one(task: Path, destination: Path, values: dict, timeout: int) -> dict:
    episode = Episode.reset(task, destination / "episode")
    task_manifest = json.loads((task / "manifest.json").read_text(encoding="utf-8"))
    boxed = task_manifest.get("protocol") == "boxed-minimal-v1"
    job = destination / "client"
    home = job / ".kimi-home"
    home.mkdir(parents=True)
    (job / ".git").mkdir()  # Bound project discovery to the isolated client directory.
    (job / "empty-skills").mkdir()
    (job / "tmp").mkdir()
    profile = job / "perception-smoke.md"
    profile.write_text(BOXED_PROFILE if boxed else PROFILE, encoding="utf-8")
    names = ["mcp__pilot__" + name for name in ("observe", "conclude", "submit")]
    (home / "config.toml").write_text(
        'telemetry = false\n[tools]\nenabled = ' + json.dumps(names) + '\n', encoding="utf-8")
    write_json_atomic(home / "mcp.json", {"mcpServers": {"pilot": {
        "command": sys.executable, "args": ["-m", "cad_evoloop.posttrain.smoke_mcp", str(episode.root)],
        "cwd": str(job), "env": {"PYTHONPATH": str(ROOT / "src"),
                                  "KIMI_MODEL_API_KEY": "", "KIMI_MODEL_BASE_URL": ""},
        "startupTimeoutMs": 15000, "toolTimeoutMs": 15000}}})
    public = json.loads((episode.root / "input/task.json").read_text(encoding="utf-8"))
    prompt = "Solve this public task. Return the final answer via submit.\n" + json.dumps(public, ensure_ascii=False)
    (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
    invocation = find_kimi_invocation(ROOT, None)
    command = [*invocation, "--agent-file", str(profile), "--skills-dir", str(job / "empty-skills"),
               "--prompt", prompt, "--output-format", "stream-json"]
    metadata = {"model": values["KIMI_MODEL_NAME"], "harness": "native-kimi-code-public-mcp-only",
                "cli_sha256": sha256_file(Path(invocation[-1])), "allowed_tools": names,
                "profile_sha256": sha256_file(profile), "timeout_seconds": timeout,
                "security": "capability restriction; not an OS sandbox; no shell/read/network/code execution tools",
                "gt_feedback": False, "task_id": task.name, "status": "running"}
    metadata["protocol"] = task_manifest.get("protocol", "legacy")
    metadata["label_status"] = task_manifest.get("label_status", "reference_fixture")
    metadata["score_semantics"] = ("agreement_with_model_proposed_label" if
                                    metadata["label_status"] == "model_proposed_not_gt" else "reference_agreement")
    if metadata["label_status"] == "unlabeled_probe":
        metadata["score_semantics"] = "ungraded_no_reference_label"
    write_json_atomic(destination / "run.json", metadata)
    environment = os.environ.copy()
    environment.update(values)
    environment.update({"KIMI_CODE_HOME": str(home), "KIMI_DISABLE_TELEMETRY": "1",
                        "KIMI_SHELL_PATH": "C:/Program Files/Git/bin/bash.exe",
                        "TEMP": str(job / "tmp"), "TMP": str(job / "tmp"),
                        "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "drain",
                        "KIMI_CODE_BACKGROUND_PRINT_WAIT_CEILING_S": str(timeout)})
    started = time.monotonic()
    timed_out = False
    with (destination / "kimi-events.jsonl").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=job, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
            process.wait(timeout=30)
    metadata.update({"exit_code": process.returncode, "timed_out": timed_out,
                     "elapsed_seconds": round(time.monotonic() - started, 2)})
    state = json.loads((episode.root / "episode.json").read_text(encoding="utf-8"))
    if state["status"] == "submitted":
        verdict = grade_episode(task, Episode(episode.root))
        metadata.update({"status": "graded", "passed": verdict["passed"], "score": verdict["score"],
                         "checks": verdict["checks"]})
        if verdict.get("human_review_required"):
            metadata.update({"status": "answer_review_required", "passed": None, "score": None,
                             "review_reason": verdict["reason"]})
    else:
        metadata.update({"status": "timeout" if timed_out else "no_submission", "passed": None})
    events = [json.loads(line) for line in (episode.root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    metadata["observations"] = sum(event["event_type"] == "observation_returned" for event in events)
    metadata["findings"] = sum(event["event_type"] == "observation_conclusion" for event in events)
    write_json_atomic(destination / "run.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--bundle", type=Path, default=ROOT / "evals/data/posttrain/pilot-r4")
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    values = parse_dotenv(ROOT / "evals/Paper_filmcooling/kimi/.env")
    validate_kimi_env(values)
    rows, skipped = [], []
    for task in sorted((args.bundle / "tasks").iterdir()):
        if args.tasks and task.name not in args.tasks:
            continue
        manifest = json.loads((task / "manifest.json").read_text(encoding="utf-8"))
        if not manifest.get("diagnostic_eligible", True):
            skipped.append({"task_id": task.name, "reason": "Annotation quarantined pending review; not a model failure"})
            continue
        kind = json.loads((task / "private/verifier.json").read_text(encoding="utf-8"))["kind"]
        if kind not in {"json_fields", "ungraded_answer"}:
            skipped.append({"task_id": task.name, "reason": "Requires separate code execution sandbox"})
            continue
        row = run_one(task, output / task.name, values, args.timeout)
        rows.append(row)
        write_json_atomic(output / "summary.json", {"runs": rows, "skipped": skipped})
        print(json.dumps(row), flush=True)
    write_json_atomic(output / "summary.json", {"runs": rows, "skipped": skipped})


if __name__ == "__main__":
    main()
