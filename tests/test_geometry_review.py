from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation import geometry_review
from cad_evoloop.evaluation.geometry_review import generate_geometry_review_bundle
from cad_evoloop.evaluation.human_review import (
    GeometryReviewHandler,
    HumanReviewStore,
    _ReviewServer,
)
from cad_evoloop.ledger.ledger import sha256_file


def _campaign(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    source = workspace / ".local/datasets/geometry/manifest.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": [{
            "sample_id": "sample:1", "dataset": "ortho2cad", "task": "Build the part",
            "ground_truth_step": "sample/ground-truth.step",
        }],
    }), encoding="utf-8")
    truth = source.parent / "sample/ground-truth.step"
    truth.parent.mkdir()
    truth.write_bytes(b"step")
    campaign = workspace / "evals/geometry-benchmarks/batch/pilot"
    job = campaign / "sample-1/model-a"
    attempt = job / "attempts/a001"
    (job / "input_files").mkdir(parents=True)
    attempt.mkdir(parents=True)
    (job / "input_files/input-01.png").write_bytes(b"png")
    (job / "task.json").write_text(json.dumps({
        "sample_id": "sample:1", "dataset": "ortho2cad", "task": "Build the part",
    }), encoding="utf-8")
    verdict = {
        "schema_version": "1.0", "protocol": "evocad-geometry-v2", "score": 82.0,
        "passed": False, "rubrics": [{
            "id": "voxel_iou", "status": "failed", "actual": 0.9, "minimum": 0.99,
        }],
    }
    (attempt / "geometry-verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    (attempt / "reflection.json").write_text(json.dumps({
        "failure_owner": "drawing", "observed_failures": ["IoU low"],
    }), encoding="utf-8")
    (attempt / "candidate.stl").write_bytes(b"solid test\nendsolid test\n")
    (attempt / "codex-events.jsonl").write_text(json.dumps({
        "type": "item.completed", "item": {"type": "agent_message", "text": "I will repair it."},
    }) + "\n", encoding="utf-8")
    (attempt / "reflection-events.jsonl").write_text(json.dumps({
        "type": "item.completed", "item": {"type": "agent_message", "text": "Continue."},
    }) + "\n", encoding="utf-8")
    (attempt / "mcp-audit.jsonl").write_text(json.dumps({
        "event_id": "e1", "tool": "autocad_core_start", "status": "fail",
        "duration_ms": 4.2, "arguments": {"timeout": 120000},
    }) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0", "protocol": "evocad-geometry-v2", "campaign_id": "pilot",
        "source_manifest_sha256": sha256_file(source), "manifest_sha256": "declared",
        "models": [{"name": "model-a"}], "execution": {"max_attempts": 2},
    }
    (campaign / "campaign-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = {
        "run_id": "pilot-model-a", "sample_id": "sample:1", "model": "model-a",
        "reasoning_effort": "medium", "job_dir": str(job), "status": "failed", "score": 82,
        "passed": False, "selected_attempt_id": "a001", "candidate_sha256": "candidate",
        "ground_truth_sha256": sha256_file(truth), "integrity": {"ok": True},
        "attempts": [{
            "attempt_id": "a001", "attempt_number": 1, "score": 82, "passed": False,
            "elapsed_seconds": 12.5, "return_code": 0, "timed_out": False,
            "agent_decision": "continue", "decision_reason": "A concrete repair remains.",
            "can_improve": True, "safety_stop_reason": "max_iterations",
        }],
    }
    (campaign / "results.json").write_text(json.dumps([result]), encoding="utf-8")
    return campaign, source, workspace


def _submission(target_id: str) -> dict:
    return {
        "target_id": target_id,
        "attempt_id": "a001",
        "reviewer": {"id": "reviewer-1", "expertise": "mechanical CAD"},
        "verifier_decision": "disagree",
        "strict_pass_assessment": "false_negative",
        "selected_attempt_assessment": "correct",
        "ratings": {
            "evidence_sufficiency": 4, "geometry_fidelity": 5,
            "verifier_validity": 2, "reflection_quality": 3,
        },
        "issue_types": ["verifier_threshold"],
        "recommended_action": "revise_verifier",
        "findings": [{
            "category": "verifier_threshold", "severity": "major", "location": "voxel_iou",
            "observation": "The threshold rejects an acceptable reconstruction.",
            "recommendation": "Recalibrate against expert labels.",
        }],
        "notes": "Visual evidence supports the candidate.",
        "duration_seconds": 42,
        "supersedes_review_id": None,
    }


def test_geometry_review_bundle_exports_attempt_evidence(tmp_path: Path) -> None:
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"

    payload = generate_geometry_review_bundle(campaign, output, source_manifest=source)

    assert payload["campaign"]["campaign_id"] == "pilot"
    assert payload["source_manifest_available"] is True
    run = payload["runs"][0]
    assert run["input_images"] == ["assets/sample-1/model-a/input-01.png"]
    assert len(run["input_evidence"][0]["sha256"]) == 64
    assert run["attempts"][0]["reflection"]["failure_owner"] == "drawing"
    assert run["attempts"][0]["public_events"][0]["text"] == "I will repair it."
    assert run["attempts"][0]["public_events"][1]["phase"] == "feedback"
    assert run["attempts"][0]["agent_decision"] == "continue"
    assert run["attempts"][0]["safety_stop_reason"] == "max_iterations"
    assert run["attempts"][0]["mcp_events"][0]["status"] == "fail"
    assert len(run["attempts"][0]["evidence_sha256"]) == 64
    assert (output / "review-data.json").is_file()
    assert (output / "app/vendor/three/three.module.min.js").is_file()
    assert (output / "app/vendor/three/three.core.min.js").is_file()
    assert (output / "app/index.html").is_file()
    assert payload["review_system"]["render_protocol"]["id"] == "evocad-orthographic-evidence-v1"


def test_human_review_ledger_binds_revisions_and_detects_tampering(tmp_path: Path) -> None:
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"
    payload = generate_geometry_review_bundle(campaign, output, source_manifest=source)
    ledger = workspace / "evals/geometry-benchmarks/human-reviews/pilot.jsonl"
    store = HumanReviewStore(output / "review-data.json", ledger)
    submission = _submission(payload["runs"][0]["target_id"])

    first = store.append(submission)
    revision = store.append({**submission, "verifier_decision": "partially_agree", "supersedes_review_id": first["review_id"]})

    response = store.response()
    assert response["integrity"]["ok"] is True
    assert response["active_records"] == 1
    assert response["summary"]["decisions"]["partially_agree"] == 1
    assert response["summary"]["conflicted_evidence"] == 0
    assert response["summary"]["rating_means"]["verifier_validity"] == 2.0
    assert revision["previous_record_sha256"] == first["record_sha256"]
    lines = ledger.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["notes"] = "changed"
    lines[0] = json.dumps(tampered)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert store.verify()["ok"] is False


def test_human_review_rejects_unbound_attempt(tmp_path: Path) -> None:
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"
    payload = generate_geometry_review_bundle(campaign, output, source_manifest=source)
    store = HumanReviewStore(output / "review-data.json", workspace / "reviews.jsonl")
    submission = _submission(payload["runs"][0]["target_id"])
    submission["attempt_id"] = "a999"

    with pytest.raises(ValueError, match="Unknown attempt"):
        store.append(submission)


def test_human_review_rejects_changed_visual_evidence(tmp_path: Path) -> None:
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"
    payload = generate_geometry_review_bundle(campaign, output, source_manifest=source)
    store = HumanReviewStore(output / "review-data.json", workspace / "reviews.jsonl")
    (output / payload["runs"][0]["input_images"][0]).write_bytes(b"changed")

    with pytest.raises(ValueError, match="bundle integrity failed"):
        store.append(_submission(payload["runs"][0]["target_id"]))


def test_geometry_review_frontend_contains_required_review_surfaces() -> None:
    root = Path(__file__).parents[1] / "apps/geometry-review"
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")
    for identifier in (
        "evidencePanel", "verifierPanel", "reflectionPanel", "feedbackPacket", "mcpPanel",
        "reviewForm",
    ):
        assert f'id="{identifier}"' in html
    assert 'fetch("/api/reviews"' in script
    assert "supersedes_review_id" in script
    assert 'src="app.js?v=7"' in html
    assert "truthViewer" in html and "candidateViewer" in html and "overlayViewer" in html
    viewer = (root / "geometry-viewer.js").read_text(encoding="utf-8")
    three_module = (root / "vendor/three/three.module.min.js").read_text(encoding="utf-8")
    assert "OrbitControls" in viewer
    assert "syncFrom" in viewer
    assert "AbortController" in viewer
    assert "getSharedRenderer" in viewer
    assert 'getContext("2d")' in viewer
    assert "preserveDrawingBuffer: true" in viewer
    assert 'from "./vendor/three/three.module.min.js"' in viewer
    assert 'from"./three.core.min.js"' in three_module
    assert (root / "vendor/three/three.core.min.js").stat().st_size > 300_000
    assert 'type="importmap"' not in html
    assert 'max-height: 100%' in styles
    assert 'height: clamp(260px, 38vh, 440px)' in styles
    assert 'aspect-ratio: 1' in styles
    assert 'cursor: grab' in styles
    assert 'pointer-events: auto' in styles
    assert 'import("./geometry-viewer.js?v=7")' in script
    assert 'viewport.render()' in viewer
    assert 'viewport.resize()' not in viewer


def test_geometry_review_server_rejects_duplicate_listener(tmp_path: Path) -> None:
    store = object()
    first = _ReviewServer(
        ("127.0.0.1", 0), GeometryReviewHandler,
        app_dir=tmp_path, bundle_dir=tmp_path, store=store,
    )
    try:
        host, port = first.server_address
        with pytest.raises(OSError):
            duplicate = _ReviewServer(
                (host, port), GeometryReviewHandler,
                app_dir=tmp_path, bundle_dir=tmp_path, store=store,
            )
            duplicate.server_close()
    finally:
        first.server_close()


def test_geometry_review_exports_aligned_interactive_assets(tmp_path, monkeypatch) -> None:
    trimesh = pytest.importorskip("trimesh")
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"
    ground_truth = trimesh.creation.box(extents=(10, 20, 30))
    candidate = trimesh.creation.box(extents=(8, 18, 28))
    candidate.apply_translation((100, -40, 12))

    def load_mesh(path):
        return candidate.copy() if Path(path).name == "candidate.stl" else ground_truth.copy()

    monkeypatch.setattr("cad_evoloop.evaluation.geometry_score._load_mesh", load_mesh)
    payload = generate_geometry_review_bundle(
        campaign, output, source_manifest=source, render_geometry=True,
    )

    attempt = payload["runs"][0]["attempts"][0]
    assert attempt["geometry"]["candidate"].endswith("a001-candidate.stl")
    assert attempt["geometry"]["ground_truth"].endswith("ground-truth.stl")
    assert attempt["evidence"]["geometry_assets"]["candidate"]["sha256"]
    store = HumanReviewStore(output / "review-data.json", workspace / "reviews.jsonl")
    assert store.verify_bundle()["ok"] is True


def test_candidate_alignment_uses_truth_center_without_rotation() -> None:
    trimesh = pytest.importorskip("trimesh")
    candidate = trimesh.creation.box(extents=(2, 4, 6))
    candidate.apply_translation((20, -7, 3))
    truth = trimesh.creation.box(extents=(4, 6, 8))
    truth.apply_translation((-3, 9, 12))

    aligned = geometry_review._align_candidate(candidate, truth, {"alignment": {}})

    assert aligned.bounds.mean(axis=0) == pytest.approx(truth.bounds.mean(axis=0))


def test_review_export_does_not_reuse_stale_geometry_assets(tmp_path) -> None:
    campaign, source, workspace = _campaign(tmp_path)
    output = workspace / "reports/review"
    stale = output / "assets/sample-1/model-a/a001-candidate.stl"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    payload = generate_geometry_review_bundle(
        campaign, output, source_manifest=source, render_geometry=False,
    )

    assert not stale.exists()
    assert payload["runs"][0]["attempts"][0]["geometry"]["candidate"] is None
