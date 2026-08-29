"""Dependency-free stdio MCP bridge to a running AutoCAD instance."""

from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any, Callable

import pythoncom
import pywintypes
import win32com.client


SERVER_NAME = "autocad"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"
RETRY_HRESULTS = {-2147418111, -2147417846}


def com_call(fn: Callable[[], Any], attempts: int = 30, delay: float = 0.25) -> Any:
    for attempt in range(attempts):
        try:
            return fn()
        except pywintypes.com_error as exc:
            if exc.hresult in RETRY_HRESULTS and attempt < attempts - 1:
                time.sleep(delay)
                continue
            raise


def get_app() -> Any:
    return com_call(lambda: win32com.client.GetActiveObject("AutoCAD.Application"))


def get_document(create: bool = False) -> tuple[Any, Any]:
    app = get_app()
    if com_call(lambda: app.Documents.Count) == 0:
        if not create:
            raise RuntimeError("AutoCAD has no open document")
        return app, com_call(lambda: app.Documents.Add())
    return app, com_call(lambda: app.ActiveDocument)


def wait_until_idle(doc: Any, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not str(com_call(lambda: doc.GetVariable("CMDNAMES"))):
                return
        except pywintypes.com_error:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"AutoCAD did not become idle within {timeout:g} seconds")


def tool_status(_: dict[str, Any]) -> dict[str, Any]:
    """Report the active AutoCAD version, document, command, and entity count."""
    app, doc = get_document()
    model_space = com_call(lambda: doc.ModelSpace)
    return {
        "connected": True,
        "version": str(com_call(lambda: app.Version)),
        "document": str(com_call(lambda: doc.Name)),
        "active_command": str(com_call(lambda: doc.GetVariable("CMDNAMES"))),
        "entities": int(com_call(lambda: model_space.Count)),
    }


def tool_new_document(_: dict[str, Any]) -> dict[str, Any]:
    """Create and activate a new AutoCAD document."""
    app = get_app()
    doc = com_call(lambda: app.Documents.Add())
    return {"document": str(com_call(lambda: doc.Name))}


def tool_send_command(arguments: dict[str, Any]) -> dict[str, Any]:
    """Send unrestricted AutoCAD command-line or AutoLISP input to the active document."""
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    timeout = float(arguments.get("timeout", 120))
    if timeout <= 0 or timeout > 1800:
        raise ValueError("timeout must be between 0 and 1800 seconds")
    _, doc = get_document(create=True)
    payload = command if command.endswith(("\n", "\r")) else command + "\n"
    com_call(lambda: doc.SendCommand(payload))
    wait_until_idle(doc, timeout)
    return {
        "accepted": True,
        "document": str(com_call(lambda: doc.Name)),
        "active_command": str(com_call(lambda: doc.GetVariable("CMDNAMES"))),
    }


def tool_get_variable(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read any AutoCAD system variable from the active document."""
    _, doc = get_document()
    name = str(arguments["name"])
    value = com_call(lambda: doc.GetVariable(name))
    return {"name": name, "value": list(value) if isinstance(value, tuple) else value}


def tool_set_variable(arguments: dict[str, Any]) -> dict[str, Any]:
    """Set any AutoCAD system variable in the active document."""
    _, doc = get_document()
    name = str(arguments["name"])
    value = arguments["value"]
    com_call(lambda: doc.SetVariable(name, value))
    return {"name": name, "value": value}


def tool_save(arguments: dict[str, Any]) -> dict[str, Any]:
    """Save the active AutoCAD document, optionally under a supplied path."""
    _, doc = get_document()
    path = arguments.get("path")
    if path:
        com_call(lambda: doc.SaveAs(str(path)))
    else:
        com_call(lambda: doc.Save())
    return {"saved": str(com_call(lambda: doc.FullName))}


TOOLS: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], dict[str, Any]]] = {
    "autocad_status": (tool_status, {"type": "object", "properties": {}}),
    "autocad_new_document": (tool_new_document, {"type": "object", "properties": {}}),
    "autocad_send_command": (tool_send_command, {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Complete AutoCAD command-line input or AutoLISP expression"},
            "timeout": {"type": "number", "minimum": 0, "maximum": 1800},
        },
        "required": ["command"],
    }),
    "autocad_get_variable": (tool_get_variable, {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }),
    "autocad_set_variable": (tool_set_variable, {
        "type": "object",
        "properties": {"name": {"type": "string"}, "value": {}},
        "required": ["name", "value"],
    }),
    "autocad_save": (tool_save, {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }),
}


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def receive() -> dict[str, Any] | None:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        headers = {"content-length": line.decode("ascii").split(":", 1)[1].strip()}
        while True:
            line = sys.stdin.buffer.readline()
            if line in (b"\r\n", b"\n"):
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))
    return json.loads(line)


def result(request_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    if request_id is None:
        return None
    method = message.get("method")
    if method == "initialize":
        return result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return result(request_id, {})
    if method == "tools/list":
        return result(request_id, {"tools": [
            {"name": name, "description": fn.__doc__ or name, "inputSchema": schema}
            for name, (fn, schema) in TOOLS.items()
        ]})
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name")
        if name not in TOOLS:
            return error(request_id, -32602, f"Unknown tool: {name}")
        try:
            output = TOOLS[name][0](params.get("arguments", {}))
            return result(request_id, {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}]})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    pythoncom.CoInitialize()
    try:
        while True:
            message = receive()
            if message is None:
                break
            response = handle(message)
            if response is not None:
                send(response)
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()

