"""Provider-neutral model and conversation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelCapabilities:
    tools: bool = False
    images: bool = False
    structured_output: bool = False
    resumable_conversation: bool = False
    reasoning_controls: bool = False


@dataclass(frozen=True)
class ToolRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTurn:
    content: str | None
    tool_requests: list[ToolRequest] = field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationHandle:
    provider: str
    conversation_id: str
    opaque_state: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...

    def capabilities(self) -> ModelCapabilities: ...

    def start(self, request: ModelRequest) -> tuple[ConversationHandle, ModelTurn]: ...

    def continue_(
        self, handle: ConversationHandle, request: ModelRequest,
    ) -> tuple[ConversationHandle, ModelTurn]: ...

    def cancel(self, handle: ConversationHandle) -> None: ...

