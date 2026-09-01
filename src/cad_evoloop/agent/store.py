"""Filesystem event store for resumable long-horizon projects."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from cad_evoloop.agent.events import GENESIS_HASH, create_event, validate_event
from cad_evoloop.agent.state import replay
from cad_evoloop.ledger.ledger import file_lock, validate_identifier, write_json_atomic


class ProjectStore:
    def __init__(self, root: str | Path, project_id: str) -> None:
        self.root = Path(root).resolve()
        self.project_id = validate_identifier(project_id, "project_id")
        self.project_dir = self.root / self.project_id
        self.events_path = self.project_dir / "events.jsonl"
        self.state_path = self.project_dir / "state.json"
        self.lock_path = self.project_dir / ".events.lock"

    @classmethod
    def create(
        cls,
        root: str | Path,
        project_id: str,
        goal: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> "ProjectStore":
        store = cls(root, project_id)
        store.project_dir.mkdir(parents=True, exist_ok=False)
        (store.project_dir / "artifacts").mkdir()
        store.events_path.touch()
        store.append(
            "project.created",
            {"goal": goal, "metadata": metadata or {}},
            actor="system",
            idempotency_key=f"project.created:{project_id}",
        )
        return store

    def _load_events_unlocked(self) -> list[dict[str, Any]]:
        if not self.events_path.is_file():
            raise FileNotFoundError(self.events_path)
        events = []
        previous_hash = GENESIS_HASH
        for line_number, line in enumerate(self.events_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid project event JSON at line {line_number}") from exc
            validate_event(
                event,
                project_id=self.project_id,
                expected_sequence=len(events) + 1,
                expected_previous_hash=previous_hash,
            )
            events.append(event)
            previous_hash = event["event_hash"]
        return events

    def events(self) -> list[dict[str, Any]]:
        with file_lock(self.lock_path):
            return self._load_events_unlocked()

    def load(self) -> dict[str, Any]:
        with file_lock(self.lock_path):
            events = self._load_events_unlocked()
            state = replay(self.project_id, events)
            try:
                snapshot = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                snapshot = None
            if snapshot != state:
                write_json_atomic(self.state_path, state)
            return state

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("Project event payload must be an object")
        with file_lock(self.lock_path):
            events = self._load_events_unlocked()
            if idempotency_key is not None:
                existing = next(
                    (
                        event for event in events
                        if event.get("idempotency_key") == idempotency_key
                    ),
                    None,
                )
                if existing is not None:
                    if existing["event_type"] != event_type or existing["payload"] != payload:
                        raise ValueError(
                            f"Idempotency key {idempotency_key!r} was reused with different content"
                        )
                    return replay(self.project_id, events)
            previous_hash = events[-1]["event_hash"] if events else GENESIS_HASH
            event = create_event(
                project_id=self.project_id,
                sequence=len(events) + 1,
                previous_hash=previous_hash,
                event_type=event_type,
                payload=payload,
                actor=actor,
                idempotency_key=idempotency_key,
            )
            state = replay(self.project_id, [*events, event])
            with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            write_json_atomic(self.state_path, state)
            return state

    def verify(self) -> dict[str, Any]:
        try:
            events = self.events()
            state = replay(self.project_id, events)
            snapshot = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "events": 0, "error": str(exc)}
        snapshot_matches = snapshot == state
        return {
            "ok": snapshot_matches,
            "events": len(events),
            "last_event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
            "snapshot_matches": snapshot_matches,
        }

    def add_work_unit(
        self,
        *,
        unit_id: str,
        kind: str,
        title: str,
        description: str,
        acceptance_criteria: Iterable[str],
        dependencies: Iterable[str] = (),
        max_attempts: int = 3,
        actor: str = "planner",
    ) -> dict[str, Any]:
        unit_id = validate_identifier(unit_id, "unit_id")
        return self.append(
            "work_unit.added",
            {
                "unit_id": unit_id,
                "kind": kind,
                "title": title,
                "description": description,
                "acceptance_criteria": list(acceptance_criteria),
                "dependencies": list(dependencies),
                "max_attempts": max_attempts,
            },
            actor=actor,
            idempotency_key=f"work_unit.added:{unit_id}",
        )
