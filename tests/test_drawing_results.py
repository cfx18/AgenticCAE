import json

import pytest

from cad_evoloop.posttrain import results


def row(outcome, *, submitted=True, attempted=True):
    return {"raw": outcome, "adjusted": outcome, "attempted": attempted,
            "submitted": submitted, "observations": 2, "elapsed_seconds": 10}


def test_denominators_include_timeouts_but_exclude_quarantine():
    rows = [row("agree"), row("disagree"), row("timeout", submitted=False),
            row("pending"), row("excluded", submitted=False, attempted=False)]
    report = results.summarize(rows)
    assert report["attempted"] == 4 and report["submitted"] == 3
    assert report["agreement_all"] == .25
    assert report["agreement_submitted"] == 1 / 3
    assert report["counts"]["excluded"] == 1


def test_empty_submitted_denominator_is_not_zero_accuracy():
    summary = results.summarize([row("timeout", submitted=False)])
    assert summary["agreement_all"] == 0
    assert summary["agreement_submitted"] is None


def test_original_automatic_counts_remain_distinct_from_semantic_review():
    item = {**row("pending"), "adjusted": "agree"}
    assert results.summarize([item], "raw")["agreement_all"] == 0
    assert results.summarize([item])["agreement_all"] == 1
    assert item["raw"] == "pending"


@pytest.mark.parametrize("eligible,status,passed,expected", [
    (False, "graded", True, "excluded"), (True, "timeout", None, "timeout"),
    (True, "graded", False, "disagree"), (True, "answer_review_required", None, "pending")])
def test_raw_states_do_not_turn_unscored_or_excluded_into_wrong_answers(eligible, status, passed, expected):
    run = {"task_manifest": {"diagnostic_eligible": eligible}, "learner": {"status": status, "passed": passed}}
    assert results.raw_outcome(run) == expected


def test_semantic_review_fails_if_exact_answer_has_changed(tmp_path, monkeypatch):
    config = {"batches": [{"id": "test", "bundle": "dummy"}], "semantic_reviews": [
        {"batch": "test", "task": "q", "expected": "solid", "answer": "solid body", "outcome": "agree", "note": "text only"}]}
    run = {"sample_id": "q", "task_manifest": {"diagnostic_eligible": True},
           "learner": {"status": "answer_review_required"}, "reference_answer": {"answer": "solid"},
           "learner_answer": {"answer": "void"}}

    class Store:
        bundle = {"summary": {}, "runs": [run]}

        def __init__(self, *args):
            pass

        def response(self):
            return {"records": [], "integrity": {"ok": True}}

    monkeypatch.setattr(results, "HumanReviewStore", Store)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches"):
        results.collect(path)
