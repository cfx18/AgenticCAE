from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.evaluation.campaign import value_digest
from cad_evoloop.evaluation.report import generate_campaign_report


def test_campaign_report_is_manifest_bound_and_reproducible(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    jobs = [
        {"sample_id": "sample-1", "model": "model-a"},
        {"sample_id": "sample-1", "model": "model-b"},
    ]
    body = {
        "schema_version": "1.0",
        "campaign_id": "pilot",
        "mode": "pilot",
        "models": [{"name": "model-a"}, {"name": "model-b"}],
        "execution": {"jobs": jobs},
    }
    manifest = {**body, "manifest_sha256": value_digest(body)}
    results = [
        {
            "sample_id": "sample-1", "model": "model-a", "status": "passed",
            "eqc": 100, "score": 100, "coverage": 100, "elapsed_seconds": 10,
            "selected_attempt_id": "a002", "integrity": {"ok": True},
            "attempts": [{"attempt_id": "a001", "eqc": 50}, {"attempt_id": "a002", "eqc": 100}],
        },
        {
            "sample_id": "sample-1", "model": "model-b", "status": "failed",
            "eqc": 75, "score": 100, "coverage": 75, "elapsed_seconds": 20,
            "selected_attempt_id": "a001", "integrity": {"ok": True},
            "attempts": [{"attempt_id": "a001", "eqc": 75}, {"attempt_id": "a002", "eqc": 50}],
        },
    ]
    (campaign / "campaign-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (campaign / "results.json").write_text(json.dumps(results), encoding="utf-8")

    output = tmp_path / "report"
    summary = generate_campaign_report(campaign, output)

    assert summary["manifest_sha256"] == manifest["manifest_sha256"]
    assert summary["mean_eqc"] == 87.5
    assert summary["mean_recovery_gain"] == 25.0
    assert summary["selected_not_last"] == 1
    assert {path.name for path in output.iterdir()} == {
        "summary.json", "runs.csv", "eqc-by-sample.svg", "recovery-scatter.svg", "report.md",
    }
    assert manifest["manifest_sha256"] in (output / "report.md").read_text(encoding="utf-8")
    assert "<svg" in (output / "eqc-by-sample.svg").read_text(encoding="utf-8")
