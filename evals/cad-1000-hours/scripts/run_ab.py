"""Run a resumable baseline/candidate CAD evaluation and improvement gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = EVAL_ROOT.parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def result_count(campaign: str) -> int:
    path = EVAL_ROOT / "batch" / campaign / "results.json"
    if not path.is_file():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0


class Campaign:
    def __init__(self, root: Path, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.status_path = root / "status.json"
        self.state: dict[str, Any] = {
            "schema_version": "1.0",
            "status": "starting",
            "phase": "initializing",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "pid": os.getpid(),
            "proposal": args.proposal,
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "baseline_campaign": args.baseline_campaign,
            "candidate_campaign": args.candidate_campaign,
            "expected_results": args.expected_results,
        }
        write_json_atomic(self.status_path, self.state)

    def update(self, **values: Any) -> None:
        self.state.update(values)
        self.state["updated_at"] = utc_now()
        self.state["counts"] = {
            "baseline": result_count(self.args.baseline_campaign),
            "candidate": result_count(self.args.candidate_campaign),
        }
        write_json_atomic(self.status_path, self.state)

    def run(self, phase: str, command: list[str], *, env: dict[str, str] | None = None) -> int:
        log_path = self.root / f"{phase}.log"
        self.update(status="running", phase=phase, command=command, log=str(log_path))
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(f"\n[{utc_now()}] START {' '.join(command)}\n")
            log.flush()
            process_env = (env or os.environ).copy()
            if not process_env.get("HOME") and process_env.get("USERPROFILE"):
                process_env["HOME"] = process_env["USERPROFILE"]
            process = subprocess.Popen(
                command,
                cwd=WORKSPACE,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_env,
            )
            while process.poll() is None:
                self.update(child_pid=process.pid)
                time.sleep(30)
            code = int(process.returncode)
            log.write(f"[{utc_now()}] EXIT {code}\n")
        self.update(child_pid=None, last_exit_code=code)
        return code


def batch_command(args: argparse.Namespace, campaign: str, proposal: str | None = None) -> list[str]:
    command = [
        sys.executable, str(SCRIPT_ROOT / "batch_codex.py"),
        "--campaign", campaign,
        "--model", args.model,
        "--reasoning-effort", args.reasoning_effort,
        "--all-samples",
        "--max-attempts", str(args.max_attempts),
        "--timeout", str(args.timeout),
    ]
    if proposal:
        command.extend(["--proposal", proposal])
    return command


def report_command(results: Path, output: Path, model: str) -> list[str]:
    return [
        sys.executable, str(SCRIPT_ROOT / "system_improve.py"), "report",
        "--results", str(results), "--output", str(output),
        "--model", model, "--tests-passed",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--baseline-campaign", required=True)
    parser.add_argument("--candidate-campaign", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--expected-results", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = EVAL_ROOT / "improvement" / "campaigns" / f"{args.baseline_campaign}__{args.candidate_campaign}"
    root.mkdir(parents=True, exist_ok=True)
    runner = Campaign(root, args)
    try:
        for phase, command in (
            ("baseline", batch_command(args, args.baseline_campaign)),
            ("candidate", batch_command(args, args.candidate_campaign, args.proposal)),
        ):
            code = runner.run(phase, command)
            if code != 0:
                raise RuntimeError(f"{phase} batch exited with code {code}")
            if result_count(command[command.index("--campaign") + 1]) != args.expected_results:
                raise RuntimeError(f"{phase} batch did not produce {args.expected_results} results")

        test_env = os.environ.copy()
        test_env["PYTHONPATH"] = str(EVAL_ROOT)
        tests = [
            sys.executable, "-m", "pytest",
            "mcp/tests", "evals/cad-1000-hours/runledger/tests",
            "evals/cad-1000-hours/scripts/tests", "evals/cad-1000-hours/verifier/tests",
            "evals/cad-1000-hours/verifier/vlm/tests", "evals/cad-1000-hours/improvement/tests",
            "evals/cad-1000-hours/adaptive/tests", "-q",
        ]
        if runner.run("tests", tests, env=test_env) != 0:
            raise RuntimeError("test suite failed")

        proposal_root = EVAL_ROOT / "improvement" / "proposals" / args.proposal
        baseline_report = proposal_root / "baseline-report.json"
        candidate_report = proposal_root / "candidate-report.json"
        baseline_results = EVAL_ROOT / "batch" / args.baseline_campaign / "results.json"
        candidate_results = EVAL_ROOT / "batch" / args.candidate_campaign / "results.json"
        if runner.run("baseline-report", report_command(baseline_results, baseline_report, args.model)) != 0:
            raise RuntimeError("baseline report failed")
        if runner.run("candidate-report", report_command(candidate_results, candidate_report, args.model)) != 0:
            raise RuntimeError("candidate report failed")
        gate = [
            sys.executable, str(SCRIPT_ROOT / "system_improve.py"), "gate",
            "--proposal", args.proposal,
            "--baseline-report", str(baseline_report),
            "--candidate-report", str(candidate_report),
        ]
        if runner.run("gate", gate) != 0:
            raise RuntimeError("improvement gate command failed")
        manifest = json.loads((proposal_root / "manifest.json").read_text(encoding="utf-8"))
        gate_result = manifest.get("gate") or {}
        runner.update(
            status="completed",
            phase="done",
            gate_passed=bool(gate_result.get("passed")),
            finished_at=utc_now(),
        )
        return 0
    except Exception as exc:
        runner.update(status="failed", phase="stopped", error=repr(exc), finished_at=utc_now())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
