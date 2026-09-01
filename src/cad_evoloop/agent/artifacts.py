"""Typed, content-addressed engineering artifact definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    uri: str
    sha256: str
    byte_size: int
    media_type: str
    producer_work_unit: str | None = None
    parents: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.kind or not self.uri or not self.media_type:
            raise ValueError("Artifact identity, kind, URI, and media type are required")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("Artifact sha256 must be a lowercase 64-character digest")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size < 0
        ):
            raise ValueError("Artifact byte_size must not be negative")
        if len(self.parents) != len(set(self.parents)):
            raise ValueError("Artifact parents must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["parents"] = list(self.parents)
        return value
