from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.agent import ProjectKernel, ProjectStore
from cad_evoloop.agent.executors import HumanClarificationExecutor
from cad_evoloop.evaluation.review_feedback import submit_human_clarification


def test_human_clarification_gate_blocks_and_resumes(tmp_path: Path) -> None:
    store = ProjectStore.create(tmp_path / "projects", "sample-1", "Resolve ambiguity")
    feedback = tmp_path / "feedback.json"
    feedback.write_text(json.dumps({
        "sample_id": "sample:1",
        "route": "human_clarification",
        "requires_human_clarification": True,
        "clarification_questions": ["What is the first step height?"],
        "reviews": [],
    }), encoding="utf-8")
    store.register_artifact(
        feedback, artifact_id="human-feedback", kind="human_feedback",
    )
    store.add_work_unit(
        unit_id="human-clarification",
        kind="human_clarification",
        phase="requirements",
        title="Human clarification",
        description="Wait for a missing dimension",
        acceptance_criteria=["Human response is available"],
        input_artifact_ids=["human-feedback"],
        max_attempts=2,
        parameters={
            "sample_id": "sample:1", "feedback_artifact_id": "human-feedback",
        },
    )
    kernel = ProjectKernel(store, {
        "human_clarification": HumanClarificationExecutor(store),
    })

    kernel.run()

    blocked = store.load()["work_units"]["human-clarification"]
    assert blocked["status"] == "blocked"
    assert blocked["evidence"][0]["questions"] == ["What is the first step height?"]

    response = tmp_path / "response.json"
    response.write_text(json.dumps({"first_step_height_mm": 12.5}), encoding="utf-8")
    submit_human_clarification(store.project_dir, response)
    kernel.run()

    state = store.load()
    assert state["status"] == "completed"
    assert state["work_units"]["human-clarification"]["status"] == "succeeded"
    resolved = state["artifacts"]["human-feedback-resolved"]
    value = json.loads((store.project_dir / resolved["uri"]).read_text(encoding="utf-8"))
    assert value["clarification_responses"][0]["content"]["first_step_height_mm"] == 12.5
