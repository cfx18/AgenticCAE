"""Isolated AutoCAD Core Console jobs for unattended CAD generation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
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
        topology_plugin: Path | None = None,
        max_history: int = 100,
    ) -> None:
        self.workspace = workspace.resolve()
        self.executable = executable.resolve()
        self.default_template = default_template.resolve()
        self.topology_plugin = topology_plugin.resolve() if topology_plugin else None
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
        operation_manifest: list[dict[str, Any]] | None = None,
        capture_boolean_lineage: bool = True,
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
        operation_manifest = operation_manifest or []
        if not isinstance(operation_manifest, list) or any(not isinstance(item, dict) for item in operation_manifest):
            raise ValueError("operation_manifest must be an array of objects")

        job_id = uuid.uuid4().hex
        job_dir = self.workspace / "mcp" / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload_path = job_dir / "payload.lsp"
        script_path = job_dir / "run.scr"
        success_path = job_dir / "success.txt"
        handles_path = job_dir / "final-solid-handles.txt"
        lineage_before_path = job_dir / "topology-before.json"
        lineage_after_path = job_dir / "topology-after.json"
        working_path = job_dir / "working.dwg"
        shutil.copy2(seed, working_path)
        payload_path.write_text(
            "(vl-load-com)\n"
            + lisp.rstrip()
            + "\n"
            + f'(setq mcp-handles-file (open "{lisp_string(handles_path)}" "w"))\n'
            + '(if (setq mcp-solids (ssget "_X" \'((0 . "3DSOLID"))))\n'
            + '  (progn (setq mcp-index 0) (repeat (sslength mcp-solids)\n'
            + '    (write-line (cdr (assoc 5 (entget (ssname mcp-solids mcp-index)))) mcp-handles-file)\n'
            + '    (setq mcp-index (1+ mcp-index)))))\n'
            + '(close mcp-handles-file)\n'
            + "(command \"_.QSAVE\")\n"
            + f'(setq mcp-success-file (open "{lisp_string(success_path)}" "w"))\n'
            + '(write-line "ok" mcp-success-file)\n'
            + "(close mcp-success-file)\n(princ)\n",
            encoding="utf-8",
            newline="\n",
        )
        lineage_enabled = bool(
            capture_boolean_lineage
            and self.topology_plugin is not None
            and self.topology_plugin.is_file()
        )
        lineage_prefix = (
            f'_.NETLOAD\n"{lisp_string(self.topology_plugin)}"\n'
            'EVOCAD_EXPORT_LINEAGE_BEFORE\n'
            if lineage_enabled else ""
        )
        lineage_suffix = "EVOCAD_EXPORT_LINEAGE_AFTER\n" if lineage_enabled else ""
        script_path.write_text(
            '(setvar "SECURELOAD" 0)\n'
            + lineage_prefix
            + f'(load "{lisp_string(payload_path)}")\n'
            + lineage_suffix
            + '_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        request_path = job_dir / "request.json"
        request_path.write_text(json.dumps({
            "input_path": str(seed),
            "output_path": str(output),
            "timeout_seconds": timeout,
            "lisp_length": len(lisp),
            "operation_manifest": operation_manifest,
            "capture_boolean_lineage": lineage_enabled,
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
            "operation_manifest": operation_manifest,
            "boolean_lineage_capture": {
                "enabled": lineage_enabled,
                "before_path": str(lineage_before_path) if lineage_enabled else None,
                "after_path": str(lineage_after_path) if lineage_enabled else None,
                "status": "pending" if lineage_enabled else "disabled",
            },
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
            args=(
                job_id, working_path, script_path, output, success_path, handles_path,
                lineage_before_path, lineage_after_path, lineage_enabled, timeout, cancel_event,
            ),
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
        handles_path: Path,
        lineage_before_path: Path,
        lineage_after_path: Path,
        lineage_enabled: bool,
        timeout: float,
        cancel_event: threading.Event,
    ) -> None:
        started = time.monotonic()
        stdout_path = script.parent / "stdout.log"
        stderr_path = script.parent / "stderr.log"
        diagnostic = None
        try:
            environment = None
            if lineage_enabled:
                environment = dict(os.environ)
                environment["EVOCAD_LINEAGE_BEFORE_OUTPUT"] = str(lineage_before_path)
                environment["EVOCAD_LINEAGE_AFTER_OUTPUT"] = str(lineage_after_path)
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
                env=environment,
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
                observed_handles = (
                    [line.strip() for line in handles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                    if handles_path.is_file() else []
                )
                with self._lock:
                    self._jobs[job_id]["observed_solid_handles"] = observed_handles
                    capture = self._jobs[job_id]["boolean_lineage_capture"]
                    before_exists = lineage_before_path.is_file()
                    after_exists = lineage_after_path.is_file()
                    capture["status"] = (
                        "succeeded" if before_exists and after_exists
                        else "partial" if before_exists or after_exists else "unavailable"
                    )
                    capture["before_exists"] = before_exists
                    capture["after_exists"] = after_exists
                    self._jobs[job_id]["operation_manifest"] = [
                        {
                            **item,
                            "observed_entity_handles": observed_handles,
                            "mcp_job_id": job_id,
                            "input_path": str(self._jobs[job_id]["input_path"]),
                            "output_path": str(self._jobs[job_id]["output_path"]),
                            "topology_before_path": str(lineage_before_path) if before_exists else None,
                            "topology_after_path": str(lineage_after_path) if after_exists else None,
                        }
                        for item in self._jobs[job_id]["operation_manifest"]
                    ]
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
