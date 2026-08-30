from __future__ import annotations

import json

from PIL import Image

from cad_evoloop.evaluation.geometry_report import generate_geometry_campaign_report


def test_generates_geometry_report_and_trajectory_figure(tmp_path) -> None:
    campaign = tmp_path / "campaign"
    output = tmp_path / "report"
    campaign.mkdir()
    (campaign / "campaign-manifest.json").write_text(json.dumps({
        "campaign_id": "test",
        "protocol": "evocad-geometry-v2",
        "manifest_sha256": "a" * 64,
    }), encoding="utf-8")
    (campaign / "results.json").write_text(json.dumps([{
        "sample_id": "sample:1",
        "model": "model",
        "passed": False,
        "score": 98.0,
        "selected_attempt_id": "a002",
        "integrity": {"ok": True},
        "attempts": [
            {"attempt_id": "a001", "attempt_number": 1, "score": 70, "passed": False, "elapsed_seconds": 10, "usage": {}},
            {"attempt_id": "a002", "attempt_number": 2, "score": 98, "passed": False, "elapsed_seconds": 12, "usage": {}},
        ],
    }]), encoding="utf-8")

    summary = generate_geometry_campaign_report(campaign, output)

    assert summary["mean_recovery_gain"] == 28.0
    assert (output / "attempts.csv").is_file()
    assert (output / "report.md").is_file()
    with Image.open(output / "repair-trajectories.png") as image:
        assert image.size == (1600, 900)


def test_report_handles_empty_campaign(tmp_path) -> None:
    campaign = tmp_path / "campaign"
    output = tmp_path / "report"
    campaign.mkdir()
    (campaign / "campaign-manifest.json").write_text(json.dumps({
        "campaign_id": "empty",
        "protocol": "evocad-geometry-v2",
        "manifest_sha256": "b" * 64,
    }), encoding="utf-8")
    (campaign / "results.json").write_text("[]", encoding="utf-8")

    summary = generate_geometry_campaign_report(campaign, output)

    assert summary["runs"] == 0
    assert summary["mean_recovery_gain"] is None
    assert (output / "repair-trajectories.png").is_file()


def test_report_aggregates_large_campaign_without_legend_overflow(tmp_path) -> None:
    campaign = tmp_path / "campaign"
    output = tmp_path / "report"
    campaign.mkdir()
    (campaign / "campaign-manifest.json").write_text(json.dumps({
        "campaign_id": "large",
        "protocol": "evocad-geometry-v2",
        "manifest_sha256": "c" * 64,
    }), encoding="utf-8")
    results = []
    for index in range(50):
        model = "model-a" if index % 2 == 0 else "model-b"
        results.append({
            "sample_id": f"sample:{index}",
            "model": model,
            "passed": index % 5 == 0,
            "score": 80 + index % 20,
            "selected_attempt_id": "a002",
            "integrity": {"ok": True},
            "attempts": [
                {"attempt_id": "a001", "attempt_number": 1, "score": 70, "passed": False, "elapsed_seconds": 10},
                {"attempt_id": "a002", "attempt_number": 2, "score": 80 + index % 20, "passed": index % 5 == 0, "elapsed_seconds": 12},
            ],
        })
    (campaign / "results.json").write_text(json.dumps(results), encoding="utf-8")

    summary = generate_geometry_campaign_report(campaign, output)

    assert summary["runs"] == 50
    with Image.open(output / "repair-trajectories.png") as image:
        assert image.size == (1600, 900)
