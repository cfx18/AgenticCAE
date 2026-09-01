"""Durable receipts and reconciliation for side-effecting engineering tools."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Callable, Literal

from cad_evoloop.agent.events import canonical_json
from cad_evoloop.agent.store import ProjectStore


ReconciliationDisposition = Literal["adopt", "compensate", "retry"]


@dataclass(frozen=True)
class ReconciliationResult:
    disposition: ReconciliationDisposition
    summary: str
    result: dict[str, Any] = field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()


class OperationNeedsReconciliation(RuntimeError):
    pass


class OperationCompensated(RuntimeError):
    pass


class OperationBroker:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    @staticmethod
    def request_digest(name: str, arguments: dict[str, Any]) -> str:
        payload = canonical_json({"name": name, "arguments": arguments})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(
        self,
        *,
        operation_id: str,
        work_unit_id: str,
        execution_id: str,
        name: str,
        arguments: dict[str, Any],
        action: Callable[[], dict[str, Any]],
        reconcile: Callable[[dict[str, Any]], ReconciliationResult] | None = None,
        actor: str = "tool-broker",
    ) -> dict[str, Any]:
        digest = self.request_digest(name, arguments)
        state = self.store.load()
        existing = state["operations"].get(operation_id)
        if existing is not None:
            if existing["name"] != name or existing["request_digest"] != digest:
                raise ValueError("Operation identifier was reused with a different request")
            if existing["status"] == "completed":
                return existing["result"]
            if existing["status"] == "compensated":
                raise OperationCompensated(existing["reconciliation_summary"])
            if existing["status"] == "running":
                state = self.store.append(
                    "operation.uncertain",
                    {
                        "operation_id": operation_id,
                        "error": "Recovered an operation without a terminal receipt",
                    },
                    actor=actor,
                    idempotency_key=f"operation.uncertain:{operation_id}:{existing['attempts']}",
                )
                existing = state["operations"][operation_id]
            if existing["status"] == "uncertain":
                if reconcile is None:
                    raise OperationNeedsReconciliation(operation_id)
                resolution = reconcile(existing)
                state = self.store.append(
                    "operation.reconciled",
                    {
                        "operation_id": operation_id,
                        "disposition": resolution.disposition,
                        "summary": resolution.summary,
                        "result": resolution.result,
                        "artifact_ids": list(resolution.artifact_ids),
                    },
                    actor=actor,
                    idempotency_key=f"operation.reconciled:{operation_id}:{existing['attempts']}",
                )
                existing = state["operations"][operation_id]
                if existing["status"] == "completed":
                    return existing["result"]
                if existing["status"] == "compensated":
                    raise OperationCompensated(resolution.summary)
            if existing["status"] == "retryable":
                self.store.append(
                    "operation.retry_started",
                    {
                        "operation_id": operation_id,
                        "work_unit_id": work_unit_id,
                        "execution_id": execution_id,
                    },
                    actor=actor,
                    idempotency_key=f"operation.retry_started:{operation_id}:{existing['attempts'] + 1}",
                )
        else:
            self.store.append(
                "operation.started",
                {
                    "operation_id": operation_id,
                    "work_unit_id": work_unit_id,
                    "execution_id": execution_id,
                    "name": name,
                    "arguments": arguments,
                    "request_digest": digest,
                },
                actor=actor,
                idempotency_key=f"operation.started:{operation_id}",
            )

        active_attempt = self.store.load()["operations"][operation_id]["attempts"]

        try:
            result = action()
            if not isinstance(result, dict):
                raise TypeError("Tool operation result must be an object")
        except Exception as exc:
            self.store.append(
                "operation.uncertain",
                {"operation_id": operation_id, "error": repr(exc)},
                actor=actor,
                idempotency_key=f"operation.uncertain:{operation_id}:{active_attempt}",
            )
            raise
        self.store.append(
            "operation.completed",
            {"operation_id": operation_id, "result": result, "artifact_ids": []},
            actor=actor,
            idempotency_key=f"operation.completed:{operation_id}",
        )
        return result
