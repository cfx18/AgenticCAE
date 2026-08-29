"""Asynchronous command jobs for the audited AutoCAD MCP server."""

from __future__ import annotations

from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import threading
import time
from typing import Any, Callable
import uuid


TERMINAL_STATES = {"succeeded", "failed", "cancelled", "timed_out"}
ProgressCallback = Callable[[str, int | None], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CommandJobManager:
    """Run one AutoCAD command at a time while keeping MCP responsive."""

    def __init__(
        self,
        runner: Callable[[str, float, threading.Event, ProgressCallback], dict[str, Any]],
        canceller: Callable[[int], None] | None = None,
        max_history: int = 100,
    ) -> None:
        self._runner = runner
        self._canceller = canceller
        self._max_history = max_history
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_job_id: str | None = None

    def start(self, command: str, timeout: float = 120) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        timeout = float(timeout)
        if timeout <= 0 or timeout > 1800:
            raise ValueError("timeout must be between 0 and 1800 seconds")

        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs[self._active_job_id]
                if active["status"] not in TERMINAL_STATES:
                    raise RuntimeError(f"AutoCAD command job {self._active_job_id} is still active")
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "status": "queued",
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "timeout_seconds": timeout,
                "command_length": len(command),
                "active_command": "",
                "window_handle": None,
                "result": None,
                "error": None,
            }
            cancel_event = threading.Event()
            self._jobs[job_id] = job
            self._cancel_events[job_id] = cancel_event
            self._active_job_id = job_id
            self._trim_history_locked()

        thread = threading.Thread(
            target=self._run,
            args=(job_id, command, timeout, cancel_event),
            name=f"autocad-job-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown AutoCAD command job: {job_id}")
            return dict(self._jobs[job_id])

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown AutoCAD command job: {job_id}")
            job = self._jobs[job_id]
            if job["status"] not in TERMINAL_STATES:
                self._cancel_events[job_id].set()
                job["status"] = "cancel_requested"
            window_handle = job.get("window_handle")
        if window_handle and self._canceller:
            try:
                self._canceller(int(window_handle))
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id]["cancel_error"] = str(exc)
        return self.status(job_id)

    def has_active_job(self) -> bool:
        with self._lock:
            return bool(
                self._active_job_id
                and self._jobs[self._active_job_id]["status"] not in TERMINAL_STATES
            )

    def _progress(
        self,
        job_id: str,
        active_command: str,
        window_handle: int | None = None,
    ) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["active_command"] = active_command
                if window_handle:
                    self._jobs[job_id]["window_handle"] = window_handle

    def _run(
        self,
        job_id: str,
        command: str,
        timeout: float,
        cancel_event: threading.Event,
    ) -> None:
        started = time.monotonic()
        with self._lock:
            self._jobs[job_id]["status"] = (
                "cancel_requested" if cancel_event.is_set() else "running"
            )
            self._jobs[job_id]["started_at"] = utc_now()
        cancel_detail = None
        try:
            result = self._runner(
                command,
                timeout,
                cancel_event,
                lambda active, window_handle=None: self._progress(
                    job_id, active, window_handle
                ),
            )
            status = "cancelled" if cancel_event.is_set() else "succeeded"
            error = None
        except TimeoutError as exc:
            result = None
            status = "timed_out"
            error = str(exc)
        except Exception as exc:
            result = None
            with self._lock:
                cancel_delivery_failed = bool(self._jobs[job_id].get("cancel_error"))
            if cancel_event.is_set() and not cancel_delivery_failed:
                status = "cancelled"
                error = None
                cancel_detail = str(exc)
            else:
                status = "failed"
                error = str(exc)
                cancel_detail = None

        with self._lock:
            job = self._jobs[job_id]
            job["status"] = status
            job["finished_at"] = utc_now()
            job["duration_seconds"] = round(time.monotonic() - started, 3)
            job["result"] = result
            job["error"] = error
            if cancel_detail:
                job["cancel_detail"] = cancel_detail
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _trim_history_locked(self) -> None:
        completed = [
            job_id for job_id, job in self._jobs.items()
            if job["status"] in TERMINAL_STATES
        ]
        while len(self._jobs) > self._max_history and completed:
            job_id = completed.pop(0)
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)


def make_autocad_runner(base: Any) -> Callable[
    [str, float, threading.Event, ProgressCallback], dict[str, Any]
]:
    """Create a worker that owns its COM apartment for the entire command."""

    def run(
        command: str,
        timeout: float,
        cancel_event: threading.Event,
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        base.pythoncom.CoInitialize()
        try:
            app, doc = base.get_document(create=True)
            window_handle = int(base.com_call(lambda: app.HWND))
            progress("", window_handle)
            payload = command if command.endswith(("\n", "\r")) else command + "\n"
            base.com_call(lambda: doc.SendCommand(payload))
            deadline = time.monotonic() + timeout
            escape_sent = False
            while time.monotonic() < deadline:
                active_command = ""
                command_observed = False
                try:
                    active_command = str(base.com_call(lambda: doc.GetVariable("CMDNAMES")))
                    command_observed = True
                    progress(active_command, None)
                except base.pywintypes.com_error:
                    pass

                if cancel_event.is_set() and not escape_sent:
                    base.com_call(lambda: doc.SendCommand("\x1b\x1b\x1b"))
                    escape_sent = True
                if command_observed and not active_command:
                    return {
                        "accepted": True,
                        "document": str(base.com_call(lambda: doc.Name)),
                        "active_command": "",
                    }
                time.sleep(0.1)
            if not escape_sent:
                try:
                    base.com_call(lambda: doc.SendCommand("\x1b\x1b\x1b"))
                except Exception:
                    pass
            raise TimeoutError(f"AutoCAD did not become idle within {timeout:g} seconds")
        finally:
            base.pythoncom.CoUninitialize()

    return run


class GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def post_escape_to_window(window_handle: int) -> None:
    """Post one Escape only to an AutoCAD window or its focused child."""
    user32 = ctypes.windll.user32
    if not user32.IsWindow(window_handle):
        raise RuntimeError(f"AutoCAD window no longer exists: {window_handle}")

    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
    if not thread_id:
        raise ctypes.WinError()
    info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
    target = window_handle
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        focused = int(info.hwndFocus or 0)
        if focused and (focused == window_handle or user32.IsChild(window_handle, focused)):
            target = focused

    wm_keydown = 0x0100
    wm_keyup = 0x0101
    vk_escape = 0x1B
    if not user32.PostMessageW(target, wm_keydown, vk_escape, 0):
        raise ctypes.WinError()
    if not user32.PostMessageW(target, wm_keyup, vk_escape, 0):
        raise ctypes.WinError()
