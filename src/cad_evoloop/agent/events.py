"""Canonical, hash-chained events for durable agent projects."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
import uuid


EVENT_SCHEMA_VERSION = "1.0"
GENESIS_HASH = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(event: dict[str, Any]) -> str:
    value = {key: item for key, item in event.items() if key != "event_hash"}
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def create_event(
    *,
    project_id: str,
    sequence: int,
    previous_hash: str,
    event_type: str,
    payload: dict[str, Any],
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("event_type must be a non-empty string")
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key.strip()
    ):
        raise ValueError("idempotency_key must be a non-empty string when supplied")
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": uuid.uuid4().hex,
        "project_id": project_id,
        "sequence": sequence,
        "previous_hash": previous_hash,
        "event_type": event_type,
        "occurred_at": utc_now(),
        "actor": actor,
        "idempotency_key": idempotency_key,
        "payload": payload,
    }
    event["event_hash"] = event_hash(event)
    return event


def validate_event(
    event: dict[str, Any],
    *,
    project_id: str,
    expected_sequence: int,
    expected_previous_hash: str,
) -> None:
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported project event schema: {event.get('schema_version')!r}")
    if event.get("project_id") != project_id:
        raise ValueError("Project event belongs to a different project")
    if event.get("sequence") != expected_sequence:
        raise ValueError(
            f"Project event sequence mismatch: expected {expected_sequence}, got {event.get('sequence')}"
        )
    if event.get("previous_hash") != expected_previous_hash:
        raise ValueError(f"Project event hash-chain mismatch at sequence {expected_sequence}")
    if event.get("event_hash") != event_hash(event):
        raise ValueError(f"Project event digest mismatch at sequence {expected_sequence}")
    if not isinstance(event.get("event_type"), str) or not event["event_type"]:
        raise ValueError(f"Project event type missing at sequence {expected_sequence}")
    if not isinstance(event.get("actor"), str) or not event["actor"]:
        raise ValueError(f"Project event actor missing at sequence {expected_sequence}")
    if event.get("idempotency_key") is not None and (
        not isinstance(event["idempotency_key"], str) or not event["idempotency_key"]
    ):
        raise ValueError(f"Invalid idempotency key at sequence {expected_sequence}")
    if not isinstance(event.get("payload"), dict):
        raise ValueError(f"Project event payload must be an object at sequence {expected_sequence}")
