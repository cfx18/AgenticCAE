"""Read-only native AutoCAD B-Rep topology export jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
import uuid

from .core_console import TERMINAL_STATES, decode_console_output, lisp_string


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TopologyExportJobManager:
    """Run the workspace-local managed exporter in isolated Core Console processes."""

    def __init__(self, workspace: Path, executable: Path, plugin: Path, max_history: int = 100) -> None:
        self.workspace = workspace.resolve()
        self.executable = executable.resolve()
        self.plugin = plugin.resolve()
        self.max_history = max_history
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def start(
        self, input_path: str, output_path: str, timeout: float = 120,
        query_input_path: str | None = None, query_output_path: str | None = None,
        query_source_center: list[float] | None = None,
    ) -> dict[str, Any]:
        source = self._workspace_path(input_path, "input_path")
        output = self._workspace_path(output_path, "output_path")
        timeout = float(timeout)
        if timeout <= 0 or timeout > 1800:
            raise ValueError("timeout must be between 0 and 1800 seconds")
        if not source.is_file():
            raise FileNotFoundError(f"topology input does not exist: {source}")
        if not self.executable.is_file():
            raise FileNotFoundError(f"AutoCAD Core Console not found: {self.executable}")
        if not self.plugin.is_file():
            raise FileNotFoundError(f"EvoCAD topology plugin not built: {self.plugin}")
        if bool(query_input_path) != bool(query_output_path):
            raise ValueError("query_input_path and query_output_path must be provided together")
        query_input = self._workspace_path(query_input_path, "query_input_path") if query_input_path else None
        query_output = self._workspace_path(query_output_path, "query_output_path") if query_output_path else None
        if query_input is not None and not query_input.is_file():
            raise FileNotFoundError(f"face query input does not exist: {query_input}")
        if query_source_center is not None and (
            not isinstance(query_source_center, list) or len(query_source_center) != 3
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in query_source_center)
        ):
            raise ValueError("query_source_center must be an array of three numbers")
        output.parent.mkdir(parents=True, exist_ok=True)
        if query_output is not None:
            query_output.parent.mkdir(parents=True, exist_ok=True)

        job_id = uuid.uuid4().hex
        job_dir = self.workspace / "mcp" / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        script = job_dir / "run.scr"
        query_command = "EVOCAD_LOCATE_POINTS\n" if query_input is not None else ""
        script.write_text(
            '(setvar "SECURELOAD" 0)\n'
            f'_.NETLOAD\n"{lisp_string(self.plugin)}"\n'
            'EVOCAD_EXPORT_TOPOLOGY\n'
            + query_command
            + '_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        (job_dir / "request.json").write_text(json.dumps({
            "input_path": str(source), "output_path": str(output), "timeout_seconds": timeout,
            "plugin_path": str(self.plugin),
            "query_input_path": str(query_input) if query_input else None,
            "query_output_path": str(query_output) if query_output else None,
            "query_source_center": query_source_center,
        }, indent=2) + "\n", encoding="utf-8")
        job = {
            "job_id": job_id, "backend": "core_console_topology", "status": "queued",
            "created_at": utc_now(), "started_at": None, "finished_at": None,
            "timeout_seconds": timeout, "input_path": str(source), "output_path": str(output),
            "job_dir": str(job_dir), "pid": None, "return_code": None, "error": None,
            "diagnostic": None,
            "query_output_path": str(query_output) if query_output else None,
        }
        event = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = event
            self._trim_history_locked()
        threading.Thread(
            target=self._run, args=(job_id, source, script, output, query_input, query_output, query_source_center, timeout, event),
            name=f"accoreconsole-topology-{job_id[:8]}", daemon=True,
        ).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown topology export job: {job_id}")
            return dict(self._jobs[job_id])

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown topology export job: {job_id}")
            job = self._jobs[job_id]
            process = None
            if job["status"] not in TERMINAL_STATES:
                self._cancel_events[job_id].set()
                job["status"] = "cancel_requested"
                process = self._processes.get(job_id)
        if process and process.poll() is None:
            process.terminate()
        return self.status(job_id)

    def _run(
        self, job_id: str, source: Path, script: Path, output: Path,
        query_input: Path | None, query_output: Path | None,
        query_source_center: list[float] | None,
        timeout: float, cancel_event: threading.Event,
    ) -> None:
        started = time.monotonic()
        stdout_path = script.parent / "stdout.log"
        stderr_path = script.parent / "stderr.log"
        try:
            env = dict(os.environ)
            env["EVOCAD_TOPOLOGY_OUTPUT"] = str(output)
            if query_input is not None and query_output is not None:
                env["EVOCAD_FACE_QUERY_INPUT"] = str(query_input)
                env["EVOCAD_FACE_QUERY_OUTPUT"] = str(query_output)
                if query_source_center is not None:
                    env["EVOCAD_FACE_QUERY_SOURCE_CENTER"] = ",".join(
                        format(float(value), ".17g") for value in query_source_center
                    )
            process = subprocess.Popen(
                [str(self.executable), "/i", str(source), "/s", str(script)],
                cwd=script.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
            )
            with self._lock:
                self._processes[job_id] = process
                self._jobs[job_id].update(status="running", started_at=utc_now(), pid=process.pid)
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
                raise TimeoutError(f"AutoCAD topology export exceeded {timeout:g} seconds")
            stdout_text = decode_console_output(stdout)
            stderr_text = decode_console_output(stderr)
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            if cancel_event.is_set():
                status, error = "cancelled", None
            elif process.returncode != 0:
                status, error = "failed", f"Core Console exited with code {process.returncode}"
            elif not output.is_file():
                status, error = "failed", "Topology plugin did not create its JSON artifact"
            elif query_output is not None and not query_output.is_file():
                status, error = "failed", "Topology plugin did not create its face-query artifact"
            else:
                payload = json.loads(output.read_text(encoding="utf-8"))
                status, error = "succeeded", None
                with self._lock:
                    self._jobs[job_id]["entity_count"] = len(payload.get("entities", []))
                    self._jobs[job_id]["export_error_count"] = len(payload.get("errors", []))
                    if query_output is not None:
                        query_payload = json.loads(query_output.read_text(encoding="utf-8"))
                        self._jobs[job_id]["query_count"] = len(query_payload.get("queries", []))
        except TimeoutError as exc:
            status, error = "timed_out", str(exc)
        except Exception as exc:
            status = "cancelled" if cancel_event.is_set() else "failed"
            error = None if status == "cancelled" else str(exc)
        finally:
            with self._lock:
                process = self._processes.pop(job_id, None)
                diagnostic = None
                if 'stdout_text' in locals() and status == "failed":
                    diagnostic = "\n".join(line.strip() for line in stdout_text.splitlines() if line.strip())[-4000:]
                self._jobs[job_id].update(
                    status=status, finished_at=utc_now(), duration_seconds=round(time.monotonic() - started, 3),
                    return_code=process.returncode if process else None, error=error, diagnostic=diagnostic,
                )

    def _workspace_path(self, value: str, name: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        path = Path(value).resolve()
        try:
            path.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"{name} must be inside workspace: {self.workspace}") from exc
        return path

    def _trim_history_locked(self) -> None:
        completed = [job_id for job_id, job in self._jobs.items() if job["status"] in TERMINAL_STATES]
        while len(self._jobs) > self.max_history and completed:
            job_id = completed.pop(0)
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)


def export_topology_core(
    workspace: str | Path,
    input_path: str | Path,
    output_path: str | Path,
    *,
    executable: str | Path,
    plugin: str | Path,
    timeout: float = 120,
    query_input_path: str | Path | None = None,
    query_output_path: str | Path | None = None,
    query_source_center: list[float] | None = None,
) -> dict[str, Any]:
    """Run one topology export to completion for verifier pipelines."""
    manager = TopologyExportJobManager(
        Path(workspace), Path(executable), Path(plugin), max_history=1,
    )
    job = manager.start(
        str(input_path), str(output_path), timeout,
        str(query_input_path) if query_input_path else None,
        str(query_output_path) if query_output_path else None,
        query_source_center,
    )
    deadline = time.monotonic() + timeout + 10
    while job["status"] not in TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.1)
        job = manager.status(job["job_id"])
    if job["status"] != "succeeded":
        raise RuntimeError(
            f"AutoCAD topology export {job['status']}: "
            f"{job.get('error') or job.get('diagnostic') or 'unknown error'}"
        )
    return job


def build_topology_plugin(
    workspace: str | Path,
    *,
    managed_dir: str | Path,
    compiler: str | Path | None = None,
) -> Path:
    """Compile the tracked exporter source into the ignored workspace cache."""
    workspace = Path(workspace).resolve()
    source = workspace / "mcp/autocad-topology/EvoCadTopology.cs"
    output = workspace / ".local/autocad-topology/EvoCadTopology.dll"
    managed_dir = Path(managed_dir).resolve()
    compiler = Path(compiler or (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"AutoCAD topology source is missing: {source}")
    if output.is_file() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return output
    references = [
        managed_dir / name
        for name in ("accoremgd.dll", "acdbmgd.dll", "acdbmgdbrep.dll", "acmgd.dll")
    ]
    missing = [path for path in (source, compiler, *references) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot build AutoCAD topology plugin; missing: {missing}")
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(compiler), "/nologo", "/target:library", "/optimize+",
            f"/out:{output}", *(f"/reference:{path}" for path in references), str(source),
        ],
        cwd=workspace, stdin=subprocess.DEVNULL, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        message = decode_console_output(completed.stdout + b"\n" + completed.stderr)
        raise RuntimeError(f"AutoCAD topology plugin build failed: {message.strip()}")
    return output
