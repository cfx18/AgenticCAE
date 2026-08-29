"""Isolated AutoCAD Core Console jobs for unattended CAD generation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
import uuid


TERMINAL_STATES = {"succeeded", "failed", "cancelled", "timed_out"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def decode_console_output(value: bytes) -> str:
    if not value:
        return ""
    if value.count(b"\x00") > len(value) // 4:
        return value.decode("utf-16-le", errors="replace")
    return value.decode("utf-8", errors="replace")


def lisp_string(value: Path) -> str:
    return str(value).replace("\\", "/").replace('"', '\\"')


class CoreConsoleJobManager:
    """Own isolated accoreconsole processes and their workspace artifacts."""

    def __init__(
        self,
        workspace: Path,
        executable: Path,
        default_template: Path,
        max_history: int = 100,
    ) -> None:
        self.workspace = workspace.resolve()
        self.executable = executable.resolve()
        self.default_template = default_template.resolve()
        self.max_history = max_history
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_job_id: str | None = None

    def start(
        self,
        lisp: str,
        output_path: str,
        input_path: str | None = None,
        timeout: float = 120,
    ) -> dict[str, Any]:
        if not isinstance(lisp, str) or not lisp.strip():
            raise ValueError("lisp must be a non-empty string")
        timeout = float(timeout)
        if timeout <= 0 or timeout > 1800:
            raise ValueError("timeout must be between 0 and 1800 seconds")
        output = self._workspace_path(output_path, "output_path")
        seed = self._workspace_path(input_path, "input_path") if input_path else self.default_template
        if not seed.is_file():
            raise FileNotFoundError(f"Core Console input does not exist: {seed}")
        if not self.executable.is_file():
            raise FileNotFoundError(f"AutoCAD Core Console not found: {self.executable}")
        if seed == output:
            raise ValueError("input_path and output_path must be different")

        job_id = uuid.uuid4().hex
        job_dir = self.workspace / "mcp" / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload_path = job_dir / "payload.lsp"
        script_path = job_dir / "run.scr"
        success_path = job_dir / "success.txt"
        working_path = job_dir / "working.dwg"
        shutil.copy2(seed, working_path)
        payload_path.write_text(
            "(vl-load-com)\n"
            + lisp.rstrip()
            + "\n(command \"_.QSAVE\")\n"
            + f'(setq mcp-success-file (open "{lisp_string(success_path)}" "w"))\n'
            + '(write-line "ok" mcp-success-file)\n'
            + "(close mcp-success-file)\n(princ)\n",
            encoding="utf-8",
            newline="\n",
        )
        script_path.write_text(
            '(setvar "SECURELOAD" 0)\n'
            f'(load "{lisp_string(payload_path)}")\n_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        request_path = job_dir / "request.json"
        request_path.write_text(json.dumps({
            "input_path": str(seed),
            "output_path": str(output),
            "timeout_seconds": timeout,
            "lisp_length": len(lisp),
        }, indent=2) + "\n", encoding="utf-8")

        job = {
            "job_id": job_id,
            "backend": "core_console",
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "timeout_seconds": timeout,
            "input_path": str(seed),
            "output_path": str(output),
            "job_dir": str(job_dir),
            "pid": None,
            "return_code": None,
            "error": None,
            "diagnostic": None,
        }
        cancel_event = threading.Event()
        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs[self._active_job_id]
                if active["status"] not in TERMINAL_STATES:
                    raise RuntimeError(f"Core Console job {self._active_job_id} is still active")
            self._jobs[job_id] = job
            self._cancel_events[job_id] = cancel_event
            self._active_job_id = job_id
            self._trim_history_locked()
        threading.Thread(
            target=self._run,
            args=(job_id, working_path, script_path, output, success_path, timeout, cancel_event),
            name=f"accoreconsole-{job_id[:8]}",
            daemon=True,
        ).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown Core Console job: {job_id}")
            return dict(self._jobs[job_id])

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown Core Console job: {job_id}")
            job = self._jobs[job_id]
            if job["status"] not in TERMINAL_STATES:
                self._cancel_events[job_id].set()
                job["status"] = "cancel_requested"
                process = self._processes.get(job_id)
            else:
                process = None
        if process and process.poll() is None:
            process.terminate()
        return self.status(job_id)

    def _run(
        self,
        job_id: str,
        seed: Path,
        script: Path,
        output: Path,
        success_path: Path,
        timeout: float,
        cancel_event: threading.Event,
    ) -> None:
        started = time.monotonic()
        stdout_path = script.parent / "stdout.log"
        stderr_path = script.parent / "stderr.log"
        diagnostic = None
        try:
            process = subprocess.Popen(
                [
                    str(self.executable),
                    "/i", str(seed),
                    "/s", str(script),
                ],
                cwd=script.parent,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with self._lock:
                self._processes[job_id] = process
                self._jobs[job_id]["status"] = "running"
                self._jobs[job_id]["started_at"] = utc_now()
                self._jobs[job_id]["pid"] = process.pid
            if cancel_event.is_set():
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                stdout_path.write_text(decode_console_output(stdout), encoding="utf-8")
                stderr_path.write_text(decode_console_output(stderr), encoding="utf-8")
                raise TimeoutError(f"AutoCAD Core Console exceeded {timeout:g} seconds")
            stdout_text = decode_console_output(stdout)
            stderr_text = decode_console_output(stderr)
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            if cancel_event.is_set():
                status, error = "cancelled", None
            elif process.returncode != 0:
                status, error = "failed", f"Core Console exited with code {process.returncode}"
            elif not success_path.is_file():
                status, error = "failed", "Core Console did not reach the save sentinel"
                lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
                diagnostic = "\n".join(lines[-12:])
            else:
                shutil.copy2(seed, output)
                status, error = "succeeded", None
        except TimeoutError as exc:
            status, error = "timed_out", str(exc)
        except Exception as exc:
            status = "cancelled" if cancel_event.is_set() else "failed"
            error = None if status == "cancelled" else str(exc)
        finally:
            with self._lock:
                job = self._jobs[job_id]
                process = self._processes.pop(job_id, None)
                job["status"] = status
                job["finished_at"] = utc_now()
                job["duration_seconds"] = round(time.monotonic() - started, 3)
                job["return_code"] = process.returncode if process else None
                job["error"] = error
                job["diagnostic"] = diagnostic
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _workspace_path(self, value: str | None, name: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        path = Path(value).resolve()
        try:
            path.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"{name} must be inside workspace: {self.workspace}") from exc
        return path

    def _trim_history_locked(self) -> None:
        completed = [
            job_id for job_id, job in self._jobs.items()
            if job["status"] in TERMINAL_STATES
        ]
        while len(self._jobs) > self.max_history and completed:
            job_id = completed.pop(0)
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)
