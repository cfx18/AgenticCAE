"""Detached, workspace-local process control for long geometry campaigns."""

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

from cad_evoloop.paths import project_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    os.replace(temporary, path)


def _process_exists(pid: int | None) -> bool:
    if not pid or pid < 1:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def campaign_control_dir(campaign: str) -> Path:
    if not campaign or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in campaign):
        raise ValueError("Invalid campaign identifier")
    return project_root() / "evals/geometry-benchmarks/batch" / campaign / "runner"


def start_detached_campaign(campaign: str, command: list[str]) -> dict[str, Any]:
    control_dir = campaign_control_dir(campaign)
    state_path = control_dir / "runner-state.json"
    if state_path.is_file():
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if existing.get("status") in {"launching", "running"} and _process_exists(existing.get("pid")):
            raise RuntimeError(f"Campaign runner is already active with PID {existing['pid']}")

    runner_id = f"{int(time.time())}-{os.getpid()}"
    command_path = control_dir / "command.json"
    _write_json_atomic(command_path, {"runner_id": runner_id, "argv": command})
    state = {
        "schema_version": "1.0",
        "runner_id": runner_id,
        "campaign": campaign,
        "status": "launching",
        "pid": None,
        "created_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "command": str(command_path.relative_to(project_root())).replace("\\", "/"),
        "stdout": "stdout.log",
        "stderr": "stderr.log",
    }
    _write_json_atomic(state_path, state)
    wrapper = [
        sys.executable, "-m", "cad_evoloop.evaluation.detached_campaign",
        "worker", "--control-dir", str(control_dir), "--runner-id", runner_id,
    ]
    kwargs: dict[str, Any] = {
        "cwd": project_root(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(wrapper, **kwargs)
    state["pid"] = process.pid
    state["status"] = "running"
    state["started_at"] = _utc_now()
    _write_json_atomic(state_path, state)
    return campaign_runner_status(campaign)


def campaign_runner_status(campaign: str) -> dict[str, Any]:
    control_dir = campaign_control_dir(campaign)
    state_path = control_dir / "runner-state.json"
    if not state_path.is_file():
        return {"campaign": campaign, "status": "not_started", "alive": False}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["alive"] = (
        state.get("status") in {"launching", "running"}
        and _process_exists(state.get("pid"))
    )
    campaign_dir = control_dir.parent
    results_path = campaign_dir / "agent-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    planned_path = campaign_dir / "agent-plan.json"
    planned = json.loads(planned_path.read_text(encoding="utf-8")).get("jobs", []) if planned_path.is_file() else []
    active = []
    projects = campaign_dir / "projects"
    if projects.is_dir():
        for state_file in projects.glob("*/state.json"):
            value = json.loads(state_file.read_text(encoding="utf-8"))
            unit = value.get("work_units", {}).get("geometry-reconstruction", {})
            if unit.get("status") == "running":
                active.append(value.get("metadata", {}).get("sample_id", state_file.parent.name))
    state["progress"] = {
        "planned": len(planned),
        "recorded": len(results),
        "terminal": sum(
            row.get("work_unit_status") in {"succeeded", "failed"} for row in results
        ),
        "strict_passes": sum(bool(row.get("passed")) for row in results),
        "active_samples": active,
    }
    return state


def run_worker(control_dir: Path, runner_id: str) -> int:
    control_dir = control_dir.resolve()
    control_dir.relative_to(project_root())
    state_path = control_dir / "runner-state.json"
    command_path = control_dir / "command.json"
    for _ in range(100):
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("runner_id") == runner_id and state.get("pid"):
                break
        time.sleep(0.05)
    else:
        return 2
    command = json.loads(command_path.read_text(encoding="utf-8"))
    if command.get("runner_id") != runner_id:
        return 2
    state.update(status="running", pid=os.getpid(), started_at=state.get("started_at") or _utc_now())
    _write_json_atomic(state_path, state)
    return_code = None
    error = None
    try:
        with (control_dir / "stdout.log").open("a", encoding="utf-8", newline="\n") as stdout, (
            control_dir / "stderr.log"
        ).open("a", encoding="utf-8", newline="\n") as stderr:
            completed = subprocess.run(
                command["argv"], cwd=project_root(), stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
        return_code = completed.returncode
    except Exception as exc:
        error = repr(exc)
        return_code = 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("runner_id") == runner_id:
        state.update(
            status="completed" if return_code == 0 else "failed",
            finished_at=_utc_now(), return_code=return_code, error=error,
        )
        _write_json_atomic(state_path, state)
    return int(return_code or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("worker",))
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--runner-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_worker(args.control_dir, args.runner_id))


if __name__ == "__main__":
    main()
