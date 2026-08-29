"""Audited entry point that preserves the base AutoCAD MCP tool surface."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid
import winreg

if __package__:
    from .jobs import CommandJobManager, make_autocad_runner, post_escape_to_window
    from .core_console import CoreConsoleJobManager
else:  # Supports MCP launch by absolute script path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from cad_evoloop.backends.autocad.jobs import (
        CommandJobManager,
        make_autocad_runner,
        post_escape_to_window,
    )
    from cad_evoloop.backends.autocad.core_console import CoreConsoleJobManager


WORKSPACE = Path(os.environ.get("AUTOCAD_MCP_WORKSPACE", Path.cwd())).resolve()
BASE_SERVER = Path(os.environ.get(
    "AUTOCAD_MCP_BASE_SERVER",
    WORKSPACE / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py",
)).resolve()
AUDIT_PATH = Path(
    os.environ.get(
        "AUTOCAD_MCP_AUDIT_PATH",
        WORKSPACE / "evals/cad-1000-hours/records/mcp-audit.jsonl",
    )
).resolve()
SECRET_KEYS = ("authorization", "cookie", "password", "secret", "token", "api_key", "apikey")
RUN_CONTEXT: dict[str, str | None] = {"sample_id": None, "run_id": None, "attempt_id": None}
JOB_MANAGER: CommandJobManager | None = None
CORE_MANAGER: CoreConsoleJobManager | None = None
CORE_CONSOLE = Path(os.environ.get(
    "AUTOCAD_CORE_CONSOLE",
    r"E:\AutoCAD\AutoCAD 2024\accoreconsole.exe",
)).resolve()
CORE_TEMPLATE = Path(os.environ.get(
    "AUTOCAD_CORE_TEMPLATE",
    r"C:\Users\8320\AppData\Local\Autodesk\AutoCAD 2024\R24.3\chs\Template\acadiso.dwt",
)).resolve()


def configure_stdio() -> None:
    """Keep localized AutoCAD errors valid for UTF-8 MCP transports."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def load_base_server():
    spec = importlib.util.spec_from_file_location("autocad_mcp_base", BASE_SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load AutoCAD MCP server: {BASE_SERVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inside_workspace(path: Path) -> bool:
    try:
        path.relative_to(WORKSPACE)
        return True
    except ValueError:
        return False


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(token in key.casefold() for token in SECRET_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def autocad_progids() -> list[str]:
    """Return generic and installed version-specific AutoCAD COM ProgIDs."""
    prefix = "AutoCAD.Application."
    discovered: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if name.startswith(prefix):
                    discovered.append(name)
    except OSError:
        pass

    def version_key(progid: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in progid.removeprefix(prefix).split("."))
        except ValueError:
            return ()

    return ["AutoCAD.Application", *sorted(set(discovered), key=version_key, reverse=True)]


def configure_autocad_connection(base: Any) -> None:
    """Make the base bridge work when only versioned AutoCAD ProgIDs exist."""
    candidates = autocad_progids()

    def get_app() -> Any:
        last_error: Exception | None = None
        for progid in candidates:
            try:
                return base.com_call(lambda progid=progid: base.win32com.client.GetActiveObject(progid))
            except base.pywintypes.com_error as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("No AutoCAD COM ProgID is registered")

    base.get_app = get_app


def write_audit(
    request_id: Any,
    tool: str,
    arguments: dict[str, Any],
    response: dict[str, Any] | None,
    duration_ms: float,
) -> None:
    if not inside_workspace(AUDIT_PATH):
        return
    is_error = bool(response and response.get("result", {}).get("isError"))
    event = {
        "schema_version": "1.0",
        "event_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": request_id,
        **RUN_CONTEXT,
        "actor": "autocad-mcp",
        "type": "tool.call",
        "tool": tool,
        "status": "fail" if is_error else "pass",
        "duration_ms": round(duration_ms, 3),
        "arguments": redact(arguments),
        "response": redact(response),
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
    except OSError as exc:
        print(f"AutoCAD MCP audit write failed: {exc}", file=sys.stderr)


def configure_server(base: Any) -> CommandJobManager:
    """Add audited execution tools without changing the base geometry surface."""
    global JOB_MANAGER, CORE_MANAGER
    configure_autocad_connection(base)
    manager = CommandJobManager(make_autocad_runner(base), canceller=post_escape_to_window)
    core_manager = CoreConsoleJobManager(WORKSPACE, CORE_CONSOLE, CORE_TEMPLATE)
    JOB_MANAGER = manager
    CORE_MANAGER = core_manager

    def set_run_context(arguments: dict[str, Any]) -> dict[str, Any]:
        """Associate subsequent AutoCAD calls with an evaluation run and attempt."""
        for key in RUN_CONTEXT:
            value = arguments.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be a string or null")
            RUN_CONTEXT[key] = value
        return dict(RUN_CONTEXT)

    def start_command(arguments: dict[str, Any]) -> dict[str, Any]:
        """Start unrestricted AutoCAD command-line or AutoLISP input and return a job ID immediately."""
        return manager.start(arguments.get("command"), arguments.get("timeout", 120))

    def command_status(arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the current state and AutoCAD command name for an asynchronous job."""
        return manager.status(str(arguments["job_id"]))

    def cancel_command(arguments: dict[str, Any]) -> dict[str, Any]:
        """Request Escape cancellation for a running asynchronous AutoCAD command job."""
        return manager.cancel(str(arguments["job_id"]))

    def checkpoint(arguments: dict[str, Any]) -> dict[str, Any]:
        """Save the idle active document to a workspace path as a recoverable checkpoint."""
        if manager.has_active_job():
            raise RuntimeError("Cannot checkpoint while an asynchronous command job is active")
        path_value = arguments.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError("path must be a non-empty string")
        path = Path(path_value).resolve()
        if not inside_workspace(path):
            raise ValueError(f"checkpoint path must be inside workspace: {WORKSPACE}")
        path.parent.mkdir(parents=True, exist_ok=True)
        _, doc = base.get_document()
        active_command = str(base.com_call(lambda: doc.GetVariable("CMDNAMES")))
        if active_command:
            raise RuntimeError(f"Cannot checkpoint while AutoCAD command is active: {active_command}")
        base.com_call(lambda: doc.SaveAs(str(path)))
        model_space = base.com_call(lambda: doc.ModelSpace)
        return {
            "saved": str(base.com_call(lambda: doc.FullName)),
            "entities": int(base.com_call(lambda: model_space.Count)),
            "active_command": "",
        }

    def core_start(arguments: dict[str, Any]) -> dict[str, Any]:
        """Run unrestricted AutoLISP in an isolated AutoCAD Core Console process."""
        return core_manager.start(
            arguments.get("lisp"),
            arguments.get("output_path"),
            arguments.get("input_path"),
            arguments.get("timeout", 120),
        )

    def core_status(arguments: dict[str, Any]) -> dict[str, Any]:
        """Return status and artifact paths for an isolated Core Console job."""
        return core_manager.status(str(arguments["job_id"]))

    def core_cancel(arguments: dict[str, Any]) -> dict[str, Any]:
        """Terminate only the specified isolated Core Console job process."""
        return core_manager.cancel(str(arguments["job_id"]))

    job_schema = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    }
    base.TOOLS.update({
        "autocad_set_run_context": (
            set_run_context,
            {
                "type": "object",
                "properties": {
                    "sample_id": {"type": ["string", "null"]},
                    "run_id": {"type": ["string", "null"]},
                    "attempt_id": {"type": ["string", "null"]},
                },
            },
        ),
        "autocad_start_command": (
            start_command,
            {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Complete unrestricted AutoCAD command-line input or AutoLISP expression",
                    },
                    "timeout": {"type": "number", "minimum": 0, "maximum": 1800},
                },
                "required": ["command"],
            },
        ),
        "autocad_command_status": (command_status, job_schema),
        "autocad_cancel_command": (cancel_command, job_schema),
        "autocad_checkpoint": (
            checkpoint,
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        "autocad_core_start": (
            core_start,
            {
                "type": "object",
                "properties": {
                    "lisp": {
                        "type": "string",
                        "description": "Complete unrestricted AutoLISP to run in an isolated AutoCAD Core Console process",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Workspace DWG path created by this stage",
                    },
                    "input_path": {
                        "type": "string",
                        "description": "Optional workspace DWG from a previous stage; defaults to a blank metric template",
                    },
                    "timeout": {"type": "number", "minimum": 0, "maximum": 1800},
                },
                "required": ["lisp", "output_path"],
            },
        ),
        "autocad_core_status": (core_status, job_schema),
        "autocad_core_cancel": (core_cancel, job_schema),
    })
    return manager


def main() -> None:
    configure_stdio()
    base = load_base_server()
    base.SERVER_VERSION = "0.5.0"
    configure_server(base)
    original_handle = base.handle

    def audited_handle(message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("method") != "tools/call":
            return original_handle(message)
        params = message.get("params", {})
        tool = str(params.get("name"))
        arguments = params.get("arguments", {})
        started = time.perf_counter()
        response = original_handle(message)
        write_audit(
            message.get("id"), tool, arguments, response,
            (time.perf_counter() - started) * 1000.0,
        )
        return response

    base.handle = audited_handle
    base.main()


if __name__ == "__main__":
    main()
