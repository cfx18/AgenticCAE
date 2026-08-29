from __future__ import annotations

import pytest

from cad_evoloop.evaluation.metrics import evidence_qualified_completion


def verdict() -> dict:
    return {
        "passed": True,
        "score": 100,
        "hard_gates": [{"id": "document", "status": "pass"}],
        "dimensions": [
            {"id": "width", "status": "pass", "weight": 2},
            {"id": "height", "status": "unverified", "weight": 2},
        ],
        "rubrics": [{"id": "native", "status": "pass"}],
    }


def test_eqc_penalizes_unverified_weight_even_when_nominal_score_is_100() -> None:
    result = evidence_qualified_completion(verdict())

    assert result["eqc"] == 66.67
    assert result["coverage"] == 66.67
    assert result["conditional_accuracy"] == 100.0
    assert result["success"] is False


def test_visual_evidence_can_resolve_unverified_check() -> None:
    visual = {"combined": {"resolved": [
        {"id": "height", "verdict": "pass", "accepted": True},
    ]}}

    result = evidence_qualified_completion(verdict(), visual)

    assert result["eqc"] == 100.0
    assert result["success"] is True
    assert next(item for item in result["checks"] if item["id"] == "height")[
        "evidence_source"
    ] == "visual"


def test_empty_or_infrastructure_verdict_never_completes() -> None:
    result = evidence_qualified_completion({"passed": False, "error": "verifier failed"})

    assert result["eqc"] == 0.0
    assert result["coverage"] == 0.0
    assert result["success"] is False


def test_unknown_visual_resolution_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown check ids"):
        evidence_qualified_completion(
            verdict(), {"combined": {"resolved": [{"id": "invented", "verdict": "pass"}]}},
        )


def test_duplicate_check_ids_are_rejected() -> None:
    value = verdict()
    value["rubrics"].append({"id": "width", "status": "pass"})

    with pytest.raises(ValueError, match="Duplicate check id"):
        evidence_qualified_completion(value)
