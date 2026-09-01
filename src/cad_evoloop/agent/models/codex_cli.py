"""Codex CLI compatibility provider for the model-neutral agent kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
import uuid

from cad_evoloop.agent.models.base import (
    ConversationHandle,
    ModelCapabilities,
    ModelRequest,
    ModelTurn,
)


@dataclass(frozen=True)
class CodexCLIConfig:
    cwd: Path
    artifact_root: Path
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "medium"
    executable: str | None = None
    timeout_seconds: int = 1800
    config_overrides: tuple[str, ...] = ()
    isolated: bool = True
    approve_for_me: bool = True


def build_codex_exec_command(
    *,
    executable: str,
    model: str,
    reasoning_effort: str,
    cwd: Path,
    prompt: str,
    final_path: Path,
    images: tuple[Path, ...] = (),
    thread_id: str | None = None,
    output_schema: Path | None = None,
    config_overrides: tuple[str, ...] = (),
    isolated: bool = True,
    approve_for_me: bool = True,
) -> list[str]:
    command = [executable, "exec", "--skip-git-repo-check"]
    if isolated:
        command.extend(["--ignore-user-config", "--ignore-rules"])
    if approve_for_me:
        command.append("--approve-for-me")
    command.extend([
        "--model", model,
        "--cd", str(cwd),
        "-c", f'model_reasoning_effort="{reasoning_effort}"',
    ])
    for value in config_overrides:
        command.extend(["-c", value])
    if images:
        command.append("--image")
        command.extend(str(path) for path in images)
    if output_schema is not None:
        command.extend(["--output-schema", str(output_schema)])
    command.extend(["--json", "--output-last-message", str(final_path)])
    if thread_id is not None:
        command.extend(["resume", thread_id, prompt])
    else:
        command.append(prompt)
    return command


def parse_codex_events(path: Path) -> dict[str, Any]:
    thread_id = None
    usage: dict[str, int] = {}
    errors = []
    event_types = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            event_types.append(event_type)
            if event_type == "thread.started":
                thread_id = event.get("thread_id")
            elif event_type == "turn.completed":
                usage = event.get("usage") or usage
            elif event_type in {"error", "turn.failed"}:
                errors.append(event.get("message") or event.get("error"))
    return {
        "thread_id": thread_id,
        "usage": usage,
        "errors": errors,
        "event_types": event_types,
    }


class CodexCLIProvider:
    def __init__(self, config: CodexCLIConfig) -> None:
        self.config = config
        self.cwd = config.cwd.resolve()
        self.artifact_root = config.artifact_root.resolve()
        self.executable = config.executable or shutil.which("codex")
        if not self.executable:
            raise FileNotFoundError("codex executable was not found")
        if config.timeout_seconds < 1:
            raise ValueError("Codex timeout must be positive")
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "codex-cli"

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            tools=bool(self.config.config_overrides),
            images=True,
            structured_output=True,
            resumable_conversation=True,
            reasoning_controls=True,
        )

    def start(self, request: ModelRequest) -> tuple[ConversationHandle, ModelTurn]:
        return self._invoke(request, thread_id=None)

    def continue_(
        self, handle: ConversationHandle, request: ModelRequest,
    ) -> tuple[ConversationHandle, ModelTurn]:
        if handle.provider != self.name:
            raise ValueError(f"Cannot resume a {handle.provider!r} conversation with Codex CLI")
        return self._invoke(request, thread_id=handle.conversation_id)

    def cancel(self, handle: ConversationHandle) -> None:
        if handle.provider != self.name:
            raise ValueError(f"Cannot cancel a {handle.provider!r} conversation with Codex CLI")

    def _invoke(
        self, request: ModelRequest, *, thread_id: str | None,
    ) -> tuple[ConversationHandle, ModelTurn]:
        if request.tools and not self.config.config_overrides:
            raise ValueError("Codex CLI request tools require configured MCP/tool overrides")
        invocation_id = uuid.uuid4().hex
        invocation_dir = self.artifact_root / invocation_id
        invocation_dir.mkdir()
        events_path = invocation_dir / "events.jsonl"
        stderr_path = invocation_dir / "stderr.log"
        final_path = invocation_dir / "final.txt"
        schema_path = None
        if request.response_schema is not None:
            schema_path = invocation_dir / "response-schema.json"
            schema_path.write_text(
                json.dumps(request.response_schema, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        prompt = self._render_request(request)
        command = build_codex_exec_command(
            executable=self.executable,
            model=self.config.model,
            reasoning_effort=self.config.reasoning_effort,
            cwd=self.cwd,
            prompt=prompt,
            final_path=final_path,
            images=tuple(path.resolve() for path in request.images),
            thread_id=thread_id,
            output_schema=schema_path,
            config_overrides=self.config.config_overrides,
            isolated=self.config.isolated,
            approve_for_me=self.config.approve_for_me,
        )
        (invocation_dir / "command.json").write_text(
            json.dumps(command, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        timed_out = False
        return_code = None
        try:
            with events_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open(
                "w", encoding="utf-8", newline="\n",
            ) as stderr:
                completed = subprocess.run(
                    command,
                    cwd=self.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.config.timeout_seconds,
                    check=False,
                )
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        parsed = parse_codex_events(events_path)
        resolved_thread_id = parsed["thread_id"] or thread_id
        if not resolved_thread_id:
            resolved_thread_id = f"unavailable-{invocation_id}"
        content = final_path.read_text(encoding="utf-8", errors="replace") if final_path.is_file() else None
        structured = None
        if content and request.response_schema is not None:
            try:
                candidate = json.loads(content)
                structured = candidate if isinstance(candidate, dict) else None
            except json.JSONDecodeError:
                pass
        finish_reason = "timeout" if timed_out else ("stop" if return_code == 0 else "error")
        metadata = {
            "invocation_id": invocation_id,
            "return_code": return_code,
            "timed_out": timed_out,
            "errors": parsed["errors"],
            "event_types": parsed["event_types"],
            "artifacts": {
                "directory": str(invocation_dir),
                "events": str(events_path),
                "stderr": str(stderr_path),
                "final": str(final_path),
                "schema": str(schema_path) if schema_path else None,
            },
        }
        handle = ConversationHandle(
            provider=self.name,
            conversation_id=resolved_thread_id,
            opaque_state={"latest_invocation_id": invocation_id},
        )
        return handle, ModelTurn(
            content=content,
            structured_output=structured,
            usage=parsed["usage"],
            finish_reason=finish_reason,
            provider_metadata=metadata,
        )

    @staticmethod
    def _render_request(request: ModelRequest) -> str:
        parts = [request.instructions.strip()]
        if request.messages:
            parts.extend([
                "",
                "Conversation input (JSON):",
                json.dumps(request.messages, indent=2, ensure_ascii=False),
            ])
        if request.metadata:
            parts.extend([
                "",
                "Request metadata (JSON):",
                json.dumps(request.metadata, indent=2, ensure_ascii=False),
            ])
        return "\n".join(parts).strip()
