"""Persist progress and recover interrupted BenchCAD campaigns without losing evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from cad_evoloop.evaluation.detached_campaign import _write_json_atomic
from cad_evoloop.paths import project_root


def archive_incomplete(campaign_dir: Path) -> list[str]:
    campaign_dir = campaign_dir.resolve()
    campaign_dir.relative_to(project_root().resolve())
    archived = []
    for job in sorted(campaign_dir.iterdir()):
        if not job.is_dir() or job.name.startswith("_") or (job / "result.json").exists():
            continue
        if not (job / "agent_workspace").is_dir():
            continue
        # A restarted model must not silently inherit an interrupted candidate.
        destination = campaign_dir / "_interrupted" / f"{job.name}-{time.time_ns()}"
        job.resolve().relative_to(campaign_dir)
        destination.resolve().relative_to(campaign_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        job.rename(destination)
        archived.append(str(destination.relative_to(campaign_dir)))
    return archived


def progress(campaign_dir: Path) -> dict:
    results = [json.loads(p.read_text(encoding="utf-8")) for p in campaign_dir.glob("*/result.json")]
    active = []
    for job in campaign_dir.iterdir():
        if job.is_dir() and not job.name.startswith("_") and (job / "agent_workspace").is_dir() and not (job / "result.json").exists():
            active.append({"record_id": job.name, "attempts": len(list((job / "attempts").glob("attempt-*")))})
    return {
        "completed": len(results), "scored": sum(r.get("status") == "scored" for r in results),
        "active": active,
        "non_scored": [{"record_id": r["record_id"], "status": r["status"]} for r in results if r.get("status") != "scored"],
    }


def supervise(campaign: str, mode: str) -> int:
    if not campaign or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in campaign):
        raise ValueError("Invalid campaign name")
    campaign_dir = project_root() / "reports/generated/benchcad" / campaign
    campaign_dir.mkdir(parents=True, exist_ok=True)
    control = campaign_dir / "_control"
    control.mkdir(exist_ok=True)
    status_path = control / "status.json"
    if status_path.is_file():
        previous = json.loads(status_path.read_text(encoding="utf-8"))
        _write_json_atomic(control / f"status-before-restart-{time.time_ns()}.json", previous)
    command = [
        sys.executable, "-m", "cad_evoloop.cli", "benchcad-agent-batch",
        "--data-dir", str(project_root() / ".local/benchcad-eval/family-30-v1"),
        "--campaign", campaign, "--model", "gpt-5.6-sol", "--reasoning-effort", "medium",
        "--max-records", "30", "--max-iterations", "12", "--timeout", "1800",
        "--exec-timeout", "600", "--reconstruction-mode", mode,
    ]
    _write_json_atomic(control / "command.json", command)
    attempts = []
    for recovery in range(3):
        archived = archive_incomplete(campaign_dir)
        record = {"launch": recovery + 1, "archived": archived, "started_at": datetime.now(timezone.utc).isoformat()}
        attempts.append(record)
        with (control / f"run-{time.time_ns()}.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=project_root(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            record["pid"] = child.pid
            try:
                while True:
                    return_code = child.poll()
                    state = {
                        "campaign": campaign, "reconstruction_mode": mode,
                        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                        "status": "running" if return_code is None else ("completed" if return_code == 0 else "failed"),
                        "return_code": return_code, "launches": attempts, **progress(campaign_dir),
                    }
                    _write_json_atomic(control / "status.json", state)
                    if return_code is not None:
                        break
                    time.sleep(10)
            except BaseException:
                child.terminate()
                child.wait()
                raise
        record["return_code"] = return_code
        if return_code == 0:
            return 0
        if recovery < 2:
            time.sleep(30)
    return int(return_code or 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--mode", choices=("baseline", "forced_ir", "specialist_ir"), required=True)
    args = parser.parse_args()
    raise SystemExit(supervise(args.campaign, args.mode))


if __name__ == "__main__":
    main()
