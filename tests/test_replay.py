from cad_evoloop.evaluation.replay import replay_summary


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
