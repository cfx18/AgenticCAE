"""Compile verified human reviews into hash-bound Agent feedback artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cad_evoloop.agent.store import ProjectStore
from cad_evoloop.ledger.ledger import sha256_file

from .human_review import HumanReviewStore


FEEDBACK_PROTOCOL = "evocad-human-feedback-v1"
CLARIFICATION_ISSUES = {"input_ambiguity", "ground_truth_error"}
AGENT_ISSUES = {"agent_geometry", "agent_reasoning", "attempt_selection"}
SYSTEM_ISSUES = {
    "verifier_metric", "verifier_threshold", "alignment_error", "export_error",
    "mcp_error", "harness_error",
}


def _canonical_sha256(value: Any, excluded: str | None = None) -> str:
    payload = (
        {key: item for key, item in value.items() if key != excluded}
        if excluded and isinstance(value, dict) else value
    )
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    os.replace(temporary, path)


def _active_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {
        row.get("supersedes_review_id") for row in records
        if row.get("supersedes_review_id")
    }
    return [row for row in records if row.get("review_id") not in superseded]


def _route(records: list[dict[str, Any]]) -> str:
    issues = {issue for row in records for issue in row.get("issue_types", [])}
    if issues & CLARIFICATION_ISSUES or any(
        row.get("recommended_action") in {"needs_expert", "exclude_sample"}
        for row in records
    ):
        return "human_clarification"
    if issues & AGENT_ISSUES or any(
        row.get("recommended_action") == "rerun" for row in records
    ):
        return "agent_repair"
    if issues & SYSTEM_ISSUES or any(
        row.get("recommended_action") == "revise_verifier" for row in records
    ):
        return "system_improvement"
    return "evaluation_only"


def _agent_instruction(route: str) -> str:
    if route == "agent_repair":
        return (
            "Correct every geometry or reasoning defect described by issue_types, "
            "findings, and review notes, then rerun native verification. A review's "
            "recommended_action describes evaluation workflow and never means that "
            "the CAD geometry should be kept unchanged."
        )
    if route == "human_clarification":
        return (
            "Do not infer missing engineering requirements. Block modeling and ask "
            "the listed clarification questions until a bound human response exists."
        )
    if route == "system_improvement":
        return "Do not change sample geometry; route this evidence to system improvement."
    return "Retain this adjudication as evaluation evidence without changing geometry."


def _agent_visible_review(record: dict[str, Any]) -> dict[str, Any]:
    binding = record["binding"]
    return {
        "review_id": record["review_id"],
        "created_at": record.get("created_at"),
        "record_sha256": record["record_sha256"],
        "source_attempt": binding.get("attempt_id"),
        "attempt_evidence_sha256": binding.get("attempt_evidence_sha256"),
        "candidate_sha256": binding.get("candidate_sha256"),
        "verdict_sha256": binding.get("verdict_sha256"),
        "verifier_decision": record.get("verifier_decision"),
        "strict_pass_assessment": record.get("strict_pass_assessment"),
        "selected_attempt_assessment": record.get("selected_attempt_assessment"),
        "issue_types": record.get("issue_types", []),
        "recommended_action": record.get("recommended_action"),
        "findings": record.get("findings", []),
        "notes": record.get("notes", ""),
    }


def _clarification_questions(records: list[dict[str, Any]]) -> list[str]:
    questions = []
    for record in records:
        if record.get("notes", "").strip():
            questions.append(record["notes"].strip())
        for finding in record.get("findings", []):
            statement = finding.get("recommendation") or finding.get("observation")
            if statement and statement.strip():
                questions.append(statement.strip())
    if not questions:
        questions.append(
            "Specify the missing or ambiguous dimensions before geometry reconstruction."
        )
    return list(dict.fromkeys(questions))


def ingest_human_reviews(
    bundle_path: str | Path,
    reviews_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Verify a review chain and compile active records into Agent-safe feedback."""
    bundle_path = Path(bundle_path).resolve()
    reviews_path = Path(reviews_path).resolve()
    output_path = Path(output_path).resolve()
    store = HumanReviewStore(bundle_path, reviews_path)
    response = store.response()
    if not response["integrity"]["ok"]:
        raise ValueError(f"Human review integrity failed: {response['integrity']['errors']}")
    active = _active_records(response["records"])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in active:
        grouped.setdefault(record["binding"]["sample_id"], []).append(record)

    samples = {}
    system_candidates = []
    for sample_id in sorted(grouped):
        records = grouped[sample_id]
        route = _route(records)
        visible = [_agent_visible_review(record) for record in records]
        issues = sorted({issue for record in records for issue in record.get("issue_types", [])})
        sample = {
            "sample_id": sample_id,
            "route": route,
            "agent_instruction": _agent_instruction(route),
            "requires_human_clarification": route == "human_clarification",
            "issue_types": issues,
            "clarification_questions": (
                _clarification_questions(records) if route == "human_clarification" else []
            ),
            "reviews": visible,
        }
        samples[sample_id] = sample
        if route == "system_improvement" or set(issues) & SYSTEM_ISSUES:
            system_candidates.append({
                "sample_id": sample_id,
                "issue_types": issues,
                "review_ids": [record["review_id"] for record in records],
                "recommended_actions": sorted({
                    record["recommended_action"] for record in records
                }),
            })

    bundle = store.bundle
    value = {
        "schema_version": "1.0",
        "protocol": FEEDBACK_PROTOCOL,
        "source": {
            "campaign_id": bundle["campaign"]["campaign_id"],
            "campaign_manifest_sha256": bundle["campaign"]["campaign_manifest_sha256"],
            "source_manifest_sha256": bundle["campaign"].get("source_manifest_sha256"),
            "review_bundle_sha256": bundle["bundle_sha256"],
            "review_bundle_file_sha256": sha256_file(bundle_path),
            "review_ledger_sha256": sha256_file(reviews_path),
            "review_ledger_head_sha256": response["integrity"]["head_sha256"],
        },
        "active_review_count": len(active),
        "sample_count": len(samples),
        "sample_ids": list(samples),
        "samples": samples,
        "system_improvement_candidates": system_candidates,
    }
    value["feedback_manifest_sha256"] = _canonical_sha256(
        value, "feedback_manifest_sha256",
    )
    _write_json_atomic(output_path, value)
    return value


def load_human_feedback(path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("protocol") != FEEDBACK_PROTOCOL:
        raise ValueError(f"Unsupported human feedback protocol: {path}")
    declared = value.get("feedback_manifest_sha256")
    if declared != _canonical_sha256(value, "feedback_manifest_sha256"):
        raise ValueError("Human feedback manifest digest mismatch")
    sample_ids = value.get("sample_ids")
    samples = value.get("samples")
    if (
        not isinstance(sample_ids, list)
        or not isinstance(samples, dict)
        or sample_ids != list(samples)
        or value.get("sample_count") != len(sample_ids)
    ):
        raise ValueError("Human feedback sample index is inconsistent")
    return path, value


def submit_human_clarification(
    project_dir: str | Path,
    response_path: str | Path,
) -> dict[str, Any]:
    """Attach a clarification response and reopen the durable human gate."""
    project_dir = Path(project_dir).resolve()
    response_path = Path(response_path).resolve()
    store = ProjectStore(project_dir.parent, project_dir.name)
    state = store.load()
    unit = state["work_units"].get("human-clarification")
    if not unit or unit["status"] != "blocked":
        raise ValueError("Project does not have a blocked human-clarification work unit")
    feedback_id = unit["parameters"]["feedback_artifact_id"]
    response_id = f"human-clarification-response-{sha256_file(response_path)[:12]}"
    store.register_artifact(
        response_path,
        artifact_id=response_id,
        kind="human_clarification_response",
        producer_work_unit=unit["unit_id"],
        parents=(feedback_id,),
        metadata={"sample_id": unit["parameters"]["sample_id"]},
        actor="human",
    )
    return store.append(
        "work_unit.reopened",
        {"unit_id": unit["unit_id"]},
        actor="human",
        idempotency_key=f"work_unit.reopened:{response_id}",
    )
