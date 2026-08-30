from __future__ import annotations

import json
from pathlib import Path

from cad_evoloop.evaluation.campaign import value_digest
from cad_evoloop.evaluation.explorer import generate_explorer_bundle


def test_explorer_bundle_uses_cached_candidate_and_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    eval_root = workspace / "evals/cad-1000-hours"
    campaign = eval_root / "batch/pilot"
    sample = eval_root / "samples/sample-1"
    job = campaign / "sample-1/model-a"
    attempt = job / "attempts/a001"
    for path in (campaign, sample / "input_files", attempt):
        path.mkdir(parents=True, exist_ok=True)
    (sample / "task_desc.json").write_text(json.dumps({"domain": "Mechanical", "task": "Draw part"}), encoding="utf-8")
    (job / "input_files").mkdir()
    (job / "input_files/reference.png").write_bytes(b"png")
    (attempt / "candidate-render.png").write_bytes(b"png")
    (job / "verdict.json").write_text(json.dumps({
        "rubrics": [{"id": "R1", "requirement": "Has circle", "status": "unverified", "evidence": []}],
        "visual_evidence": {"combined": {"resolved": [{
            "id": "R1", "verdict": "pass", "confidence": 0.9,
            "explanation": "Circle visible", "accepted": True,
        }]}},
    }), encoding="utf-8")
    body = {
        "schema_version": "1.0", "campaign_id": "pilot", "mode": "pilot",
        "models": [{"name": "model-a"}],
        "execution": {"jobs": [{"sample_id": "sample-1", "model": "model-a"}]},
    }
    manifest = {**body, "manifest_sha256": value_digest(body)}
    result = {
        "run_id": "run-1", "sample_id": "sample-1", "model": "model-a",
        "job_dir": str(job), "status": "passed", "eqc": 100, "score": 100,
        "coverage": 75, "selected_attempt_id": "a001", "integrity": {"ok": True},
        "attempts": [{"attempt_id": "a001", "attempt_number": 1, "eqc": 100}],
    }
    (campaign / "campaign-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (campaign / "results.json").write_text(json.dumps([result]), encoding="utf-8")

    payload = generate_explorer_bundle(campaign, workspace / "reports/explorer")

    run = payload["runs"][0]
    assert run["candidate_image"].endswith("candidate-render.png")
    assert run["reference_images"][0].endswith("reference.png")
    assert run["rubrics"][0]["final_status"] == "pass"
    assert run["rubrics"][0]["evidence_source"] == "visual"
