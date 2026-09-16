"""Kimi Code transport for the existing EvoCAD geometry feedback loop."""

from __future__ import annotations

import json
from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from jsonschema import validate

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic


def read_kimi_events(path: Path) -> dict[str, Any]:
    errors = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(str(exc))
                continue
            if event.get("type") in {"error", "llm.error"}:
                errors.append(event)
    metadata_path = path.with_suffix(".transport.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    return {"thread_id": metadata.get("session_id"), "usage": {},
            "errors": errors + metadata.get("errors", [])}


def final_text(path: Path) -> str:
    result = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("role") != "assistant" or event.get("tool_calls"):
            continue
        content = event.get("content") or []
        if isinstance(content, str):
            result = content
        else:
            text = "\n".join(block.get("text", "") for block in content
                             if isinstance(block, dict) and block.get("type") == "text")
            if text.strip():
                result = text
    return result


def decision_json(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[len("```json\n"):-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()
    value = json.loads(text)
    validate(value, schema)
    return value


class KimiGeometryTransport:
    event_prefix = "kimi"
    name = "kimi-code"
    read_events = staticmethod(read_kimi_events)

    def __init__(self, *, workspace: Path, invocation: list[str], environment: dict[str, str],
                 autocad_python: Path) -> None:
        if len(invocation) != 2 or Path(invocation[1]).suffix not in {".mjs", ".js"}:
            raise ValueError("This adapter requires the workspace-local Node.js Kimi CLI")
        self.workspace = workspace.resolve()
        self.invocation = invocation
        self.environment = environment
        self.autocad_python = autocad_python
        self.version = subprocess.check_output([*invocation, "--version"], text=True).strip()
        self.runtime_identity = {
            "name": self.name, "version": self.version,
            "command": invocation, "cli_sha256": sha256_file(Path(invocation[1])),
            "usage_available": False, "schema_mode": "prompt-and-local-validation",
            "jsonschema_version": metadata.version("jsonschema"),
        }

    def _build(self, model: str, effort: str, job_dir: Path, prompt: str,
               final_path: Path, audit_path: Path | None, session_id: str | None,
               output_schema: Path | None = None) -> list[str]:
        job_dir.resolve().relative_to(self.workspace)
        if model != self.environment["KIMI_MODEL_NAME"]:
            raise ValueError("Requested model differs from the configured Kimi model")
        if effort != self.environment.get("KIMI_MODEL_THINKING_EFFORT", ""):
            raise ValueError("Requested effort differs from the configured Kimi effort")
        schema = json.loads(output_schema.read_text(encoding="utf-8")) if output_schema else None
        if schema:
            prompt += "\n\nReturn only one JSON object matching this schema:\n" + json.dumps(schema)
        argv = ["--prompt", prompt, "--output-format", "stream-json"]
        if session_id:
            argv.extend(["--session", session_id])
        request_path = final_path.parent / "kimi-request.json"
        write_json_atomic(request_path, {
            "entry": self.invocation[1], "argv": argv,
            "cwd": str(job_dir), "session_id": session_id,
            "final_path": str(final_path), "audit_path": str(audit_path) if audit_path else None,
            "schema": schema,
        })
        return [self.invocation[0], str(Path(__file__).with_name("kimi_cli_launcher.mjs")),
                str(request_path)]

    def start_command(self, executable, model, effort, job_dir, images, prompt, audit_path, final_path):
        home = job_dir / ".kimi-home"
        session = self._session(home, job_dir, None) if (home / "session_index.jsonl").is_file() else None
        return self._build(model, effort, job_dir, prompt, final_path, audit_path, session)

    def resume_command(self, executable, model, effort, job_dir, thread_id, prompt, final_path,
                       *, with_autocad, audit_path=None, output_schema=None):
        return self._build(model, effort, job_dir, prompt, final_path,
                           audit_path if with_autocad else None, thread_id, output_schema)

    def _configure(self, cwd: Path, audit_path: str | None) -> Path:
        home = cwd / ".kimi-home"
        home.mkdir(exist_ok=True)
        servers = {}
        if audit_path:
            topology = cwd / "mcp/autocad-topology/EvoCadTopology.cs"
            topology.parent.mkdir(parents=True, exist_ok=True)
            if not topology.exists():
                shutil.copy2(self.workspace / "mcp/autocad-topology/EvoCadTopology.cs", topology)
            servers["autocad"] = {
                "command": str(self.autocad_python),
                "args": [str(self.workspace / "src/cad_evoloop/backends/autocad/audited.py")],
                "cwd": str(self.workspace),
                "env": {
                    "AUTOCAD_MCP_WORKSPACE": str(cwd), "AUTOCAD_MCP_AUDIT_PATH": audit_path,
                    "AUTOCAD_MCP_BASE_SERVER": str(self.workspace / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py"),
                    "AUTOCAD_TOPOLOGY_PLUGIN": str(cwd / ".local/autocad-topology/EvoCadTopology.dll"),
                    "KIMI_MODEL_API_KEY": "", "KIMI_MODEL_BASE_URL": "",
                    "PYTHONPATH": str(self.workspace / "src"),
                },
                "startupTimeoutMs": 30000, "toolTimeoutMs": 180000,
            }
        write_json_atomic(home / "mcp.json", {"mcpServers": servers})
        (home / "config.toml").write_text(
            'telemetry = false\n\n[loop_control]\nmax_steps_per_turn = 0\n', encoding="utf-8")
        return home

    @staticmethod
    def _session(home: Path, cwd: Path, expected: str | None) -> str:
        index = home / "session_index.jsonl"
        rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
        ids = {row["sessionId"] for row in rows if Path(row["workDir"]).resolve() == cwd.resolve()}
        if expected:
            if expected not in ids:
                raise ValueError("Resumed Kimi session was not found in this job")
            return expected
        if len(ids) != 1:
            raise ValueError(f"Expected exactly one fresh Kimi session, found {len(ids)}")
        return next(iter(ids))

    def run_process(self, command, *, cwd, events_path, stderr_path, timeout, stdin_text=None):
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        home = self._configure(cwd, request["audit_path"])
        env = os.environ.copy()
        env.update(self.environment)
        env.update({
            "KIMI_CODE_HOME": str(home), "KIMI_DISABLE_TELEMETRY": "1",
            "KIMI_SHELL_PATH": r"C:\Program Files\Git\bin\bash.exe",
            "KIMI_MCP_STARTUP_TIMEOUT_MS": "30000", "KIMI_MCP_TOOL_TIMEOUT_MS": "180000",
            "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "drain",
            "KIMI_CODE_BACKGROUND_PRINT_WAIT_CEILING_S": str(timeout),
        })
        shutil.copy2(home / "mcp.json", events_path.parent / "kimi-mcp-config.json")
        timed_out = False
        errors = []
        with events_path.open("wb") as output, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=stderr,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=False)
                else:
                    process.kill()
                code = process.wait(timeout=30)
        session_id = request["session_id"]
        try:
            session_id = self._session(home, cwd, session_id)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(repr(exc))
        text = final_text(events_path)
        final_path = Path(request["final_path"])
        if text:
            if request["schema"]:
                (final_path.parent / "kimi-final.txt").write_text(text, encoding="utf-8")
                try:
                    write_json_atomic(final_path, decision_json(text, request["schema"]))
                except Exception as exc:
                    errors.append(f"Invalid structured decision: {exc}")
            else:
                final_path.write_text(text, encoding="utf-8")
        write_json_atomic(events_path.with_suffix(".transport.json"), {
            "provider": self.name, "session_id": session_id, "return_code": code,
            "timed_out": timed_out, "usage_available": False, "errors": errors,
            "request_sha256": sha256_file(Path(command[-1])),
            "events_sha256": sha256_file(events_path),
        })
        return code, timed_out
