import json

from cad_evoloop.evaluation.replay import (
    ledger_candidate_snapshot,
    replay_summary,
    retain_completed_results,
)


def test_replay_summary_separates_improvement_regression_and_incomplete() -> None:
    summary = replay_summary([
        {"old_eqc": 50, "new_eqc": 75, "status": "failed"},
        {"old_eqc": 100, "new_eqc": 100, "status": "passed"},
        {"old_eqc": 80, "new_eqc": 70, "status": "failed"},
        {"old_eqc": 40, "new_eqc": None, "status": "evaluation-incomplete"},
    ])

    assert summary == {
        "jobs": 4,
        "completed": 3,
        "evaluation_incomplete": 1,
        "old_mean_eqc": 76.67,
        "new_mean_eqc": 81.67,
        "mean_delta": 5.0,
        "old_passed": 1,
        "new_passed": 1,
        "improved": 1,
        "regressed": 1,
    }


def test_replay_resume_archives_and_retries_infrastructure_failures(tmp_path) -> None:
    results_path = tmp_path / "results.json"
    values = [
        {"sample_id": "done", "new_eqc": 100, "status": "passed"},
        {"sample_id": "retry", "new_eqc": None, "status": "evaluation-incomplete"},
    ]
    results_path.write_text(json.dumps(values), encoding="utf-8")

    retained = retain_completed_results(results_path, values)

    assert [item["sample_id"] for item in retained] == ["done"]
    assert json.loads(results_path.read_text(encoding="utf-8")) == retained
    archived = [json.loads(line) for line in (tmp_path / "retry-history.jsonl").read_text().splitlines()]
    assert archived[0]["sample_id"] == "retry"


def test_replay_uses_selected_candidate_from_ledger(tmp_path) -> None:
    run_dir = tmp_path / "records" / "sample" / "run"
    candidate = run_dir / "attempts/a002/candidate/candidate.dwg"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"frozen-dwg")
    import hashlib
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    (run_dir / "run.json").write_text(json.dumps({
        "attempts": [{
            "attempt_id": "a002",
            "artifacts": [{
                "role": "candidate",
                "stored_path": "attempts/a002/candidate/candidate.dwg",
                "sha256": digest,
            }],
        }],
    }), encoding="utf-8")

    path, sha256 = ledger_candidate_snapshot(tmp_path, {
        "sample_id": "sample", "run_id": "run", "selected_attempt_id": "a002",
    })

    assert path == candidate
    assert sha256 == digest
