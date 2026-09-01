"""Typed contracts for transitions between engineering workflow stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ArtifactRequirement:
    kind: str
    min_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("Artifact requirement kind must be non-empty")
        if isinstance(self.min_count, bool) or self.min_count < 1:
            raise ValueError("Artifact requirement min_count must be positive")


@dataclass(frozen=True)
class StageContract:
    contract_id: str
    stage: str
    input_requirements: tuple[ArtifactRequirement, ...]
    output_requirements: tuple[ArtifactRequirement, ...]
    verifier_ids: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        for label, value in (("contract_id", self.contract_id), ("stage", self.stage)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be non-empty")
        if not self.output_requirements:
            raise ValueError("A stage contract requires at least one output requirement")
        if not self.verifier_ids or any(not item.strip() for item in self.verifier_ids):
            raise ValueError("A stage contract requires non-empty verifier identifiers")
        if len(self.verifier_ids) != len(set(self.verifier_ids)):
            raise ValueError("Stage contract verifier identifiers must be unique")
        for requirements in (self.input_requirements, self.output_requirements):
            kinds = [item.kind for item in requirements]
            if len(kinds) != len(set(kinds)):
                raise ValueError("Artifact requirement kinds must be unique within each direction")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "stage": self.stage,
            "description": self.description,
            "input_requirements": [asdict(item) for item in self.input_requirements],
            "output_requirements": [asdict(item) for item in self.output_requirements],
            "verifier_ids": list(self.verifier_ids),
        }


def requirements_satisfied(
    requirements: Iterable[dict[str, Any]], artifact_kinds: Iterable[str],
) -> bool:
    counts: dict[str, int] = {}
    for kind in artifact_kinds:
        counts[kind] = counts.get(kind, 0) + 1
    return all(counts.get(item["kind"], 0) >= item["min_count"] for item in requirements)
