"""Durable human clarification gate for ambiguous engineering requirements."""

from __future__ import annotations

import json

from cad_evoloop.agent.kernel import WorkContext, WorkResult
from cad_evoloop.agent.store import ProjectStore


class HumanClarificationExecutor:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    def execute(self, context: WorkContext) -> WorkResult:
        feedback_id = context.unit["parameters"].get("feedback_artifact_id")
        artifact = context.project_state["artifacts"].get(feedback_id)
        if artifact is None or artifact["kind"] != "human_feedback":
            return WorkResult(
                outcome="failed",
                summary="Human clarification gate has no bound feedback artifact",
                error=f"Unknown human feedback artifact: {feedback_id!r}",
            )
        feedback_path = self.store.project_dir / artifact["uri"]
        feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
        responses = [
            value for value in context.project_state["artifacts"].values()
            if value["kind"] == "human_clarification_response"
            and feedback_id in value.get("parents", [])
        ]
        if responses:
            resolved_id = "human-feedback-resolved"
            resolved = context.project_state["artifacts"].get(resolved_id)
            if resolved is None:
                response_values = []
                for value in responses:
                    path = self.store.project_dir / value["uri"]
                    text = path.read_text(encoding="utf-8")
                    try:
                        content = json.loads(text)
                    except json.JSONDecodeError:
                        content = text
                    response_values.append({
                        "artifact_id": value["artifact_id"],
                        "sha256": value["sha256"],
                        "content": content,
                    })
                resolved_payload = {
                    **feedback,
                    "route": "agent_repair",
                    "requires_human_clarification": False,
                    "clarification_responses": response_values,
                }
                derived = self.store.project_dir / ".derived" / "human-feedback-resolved.json"
                derived.parent.mkdir(exist_ok=True)
                derived.write_text(
                    json.dumps(resolved_payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                self.store.register_artifact(
                    derived,
                    artifact_id=resolved_id,
                    kind="human_feedback",
                    producer_work_unit=context.unit["unit_id"],
                    parents=(feedback_id, *(value["artifact_id"] for value in responses)),
                    metadata={
                        "sample_id": feedback["sample_id"],
                        "route": "agent_repair",
                        "resolved": True,
                        "visible_to_agent": True,
                    },
                    actor="human-clarification",
                )
            return WorkResult(
                outcome="succeeded",
                summary="Human clarification response is available",
                outputs=[
                    *({"artifact_id": value["artifact_id"]} for value in responses),
                    {"artifact_id": resolved_id},
                ],
                evidence=[{
                    "sample_id": feedback["sample_id"],
                    "response_artifact_ids": [value["artifact_id"] for value in responses],
                    "resolved_feedback_artifact_id": resolved_id,
                }],
            )
        questions = feedback.get("clarification_questions") or [
            "Provide the missing engineering requirements before modeling."
        ]
        return WorkResult(
            outcome="blocked",
            summary="Geometry is waiting for human clarification",
            evidence=[{
                "sample_id": feedback["sample_id"],
                "stop_reason": "human_clarification_required",
                "questions": questions,
                "feedback_artifact_id": feedback_id,
            }],
            error="Human clarification is required before geometry reconstruction",
        )
