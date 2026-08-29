from __future__ import annotations

import json
from pathlib import Path

import improvement.manager as MODULE
from improvement import ImprovementManager


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def row(sample_id: str, score: float, coverage: float = 100.0, status: str = "passed") -> dict:
    return {
        "sample_id": sample_id,
        "score": score,
        "coverage": coverage,
        "status": status,
        "integrity": {"ok": True},
    }


def test_split_is_stable_and_reserves_ten_holdout_samples(tmp_path: Path) -> None:
    manager = ImprovementManager(tmp_path / "improvement")

    first = manager.init_split(seed=123, development=40)
    second = manager.init_split(seed=123, development=40)

    assert first == second
    assert len(first["development"]) == 40
    assert len(first["holdout"]) == 10
    assert not set(first["development"]) & set(first["holdout"])


def test_dimension_failure_is_classified_as_prompt_evidence() -> None:
    verdict = {
        "score": 28.57,
        "coverage": 82.35,
        "dimensions": [{"id": "D1", "status": "fail", "reason": "no unmatched native dimension"}],
    }

    diagnosis = MODULE.diagnose(verdict, None)

    assert diagnosis["failure_owner"] == "prompt"
    assert diagnosis["failed_dimensions"] == ["D1"]


def test_agent_finalization_rejects_unexpected_candidate_files(tmp_path: Path) -> None:
    manager = ImprovementManager(tmp_path / "improvement")
    proposal = manager.proposals_root / "p1"
    candidate = proposal / "workspace" / "allowed.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("before", encoding="utf-8")
    evidence = proposal / "evidence.json"
    write(evidence, [])
    write(proposal / "manifest.json", {
        "proposal_id": "p1",
        "status": "draft",
        "files": [{"path": "allowed.md", "before_sha256": MODULE.sha256(candidate)}],
        "evidence_sha256": MODULE.sha256(evidence),
    })
    (proposal / "workspace" / "not-allowed.py").write_text("x", encoding="utf-8")

    manifest = manager.finalize_agent_changes(proposal)

    assert manifest["status"] == "invalid"
    assert "unexpected candidate files" in manifest["invalid_reason"]


def test_agent_finalization_rejects_protected_evaluation_reads(tmp_path: Path, monkeypatch) -> None:
    eval_root = tmp_path / "evals" / "cad-1000-hours"
    workspace_root = tmp_path
    monkeypatch.setattr(MODULE, "EVAL_ROOT", eval_root)
    monkeypatch.setattr(MODULE, "WORKSPACE", workspace_root)
    manager = ImprovementManager(eval_root / "improvement")
    proposal = manager.proposals_root / "p1"
    candidate = proposal / "workspace" / "allowed.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("before", encoding="utf-8")
    evidence = proposal / "evidence.json"
    write(evidence, [])
    write(proposal / "manifest.json", {
        "proposal_id": "p1",
        "status": "draft",
        "files": [{"path": "allowed.md", "before_sha256": MODULE.sha256(candidate)}],
        "evidence_sha256": MODULE.sha256(evidence),
    })
    protected = eval_root / "samples" / "secret" / "rubrics.json"
    (proposal / "agent-events.jsonl").write_text(json.dumps({
        "item": {"command": f"Get-Content '{protected}'"},
    }) + "\n", encoding="utf-8")

    manifest = manager.finalize_agent_changes(proposal)

    assert manifest["status"] == "invalid"
    assert "protected" in manifest["invalid_reason"]


def make_gate_fixture(tmp_path: Path, components=("prompt",)):
    manager = ImprovementManager(tmp_path / "improvement")
    write(manager.split_path, {"development": ["d1", "d2"], "holdout": ["h1"]})
    proposal = manager.proposals_root / "p1"
    write(proposal / "manifest.json", {
        "proposal_id": "p1",
        "status": "proposed",
        "components": list(components),
        "files": ([{
            "component": "verifier", "path": "verify.py",
            "before_sha256": "before", "after_sha256": "after",
        }] if "verifier" in components else []),
    })
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    write(baseline, {"samples": [row("d1", 50), row("d2", 60), row("h1", 70)]})
    write(candidate, {
        "tests": {"passed": True},
        "samples": [row("d1", 55), row("d2", 60), row("h1", 71)],
    })
    return manager, baseline, candidate


def test_gate_requires_full_development_and_holdout_without_regression(tmp_path: Path) -> None:
    manager, baseline, candidate = make_gate_fixture(tmp_path)

    result = manager.gate("p1", baseline, candidate)

    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_verifier_change_needs_independent_approval(tmp_path: Path) -> None:
    manager, baseline, candidate = make_gate_fixture(tmp_path, components=("verifier",))

    rejected = manager.gate("p1", baseline, candidate)
    accepted = manager.gate("p1", baseline, candidate, independent_verifier_approval=True)

    assert rejected["passed"] is False
    assert accepted["passed"] is True


def test_unchanged_verifier_copy_does_not_need_independent_approval(tmp_path: Path) -> None:
    manager, baseline, candidate = make_gate_fixture(tmp_path, components=("verifier",))
    manifest_path = manager.proposals_root / "p1" / "manifest.json"
    manifest = MODULE.read_json(manifest_path)
    manifest["files"][0]["after_sha256"] = manifest["files"][0]["before_sha256"]
    write(manifest_path, manifest)

    result = manager.gate("p1", baseline, candidate)

    assert result["passed"] is True


def test_promotion_is_versioned_and_rollback_restores_source(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    production = workspace / "system.md"
    production.parent.mkdir()
    production.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(MODULE, "WORKSPACE", workspace)
    manager = ImprovementManager(tmp_path / "improvement")
    proposal = manager.proposals_root / "p1"
    candidate = proposal / "workspace" / "system.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("v2", encoding="utf-8")
    write(proposal / "manifest.json", {
        "proposal_id": "p1",
        "status": "gate-passed",
        "files": [{"path": "system.md", "after_sha256": MODULE.sha256(candidate)}],
    })

    manager.promote("p1")
    assert production.read_text(encoding="utf-8") == "v2"

    manager.rollback("p1")
    assert production.read_text(encoding="utf-8") == "v1"


def test_static_validation_checks_prompt_placeholders_and_production_hashes(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(MODULE, "WORKSPACE", workspace)
    manager = ImprovementManager(tmp_path / "improvement")
    proposal = manager.proposals_root / "p1"
    relative = "evals/cad-1000-hours/prompts/modeling.md"
    placeholders = (
        "$sample_id $run_id $attempt_id $skill_path $geometry_checkpoint "
        "$annotation_checkpoint $candidate"
    )
    production = workspace / relative
    production.parent.mkdir(parents=True)
    production.write_text(placeholders, encoding="utf-8")
    candidate = proposal / "workspace" / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text(placeholders + " audit", encoding="utf-8")
    write(proposal / "workspace" / "change-proposal.json", {
        key: [] for key in (
            "evidence_summary", "failure_owners", "changed_files",
            "expected_impact", "risks", "validation_plan",
        )
    })
    write(proposal / "manifest.json", {
        "proposal_id": "p1",
        "files": [{"path": relative, "before_sha256": MODULE.sha256(production)}],
    })

    result = manager.validate_static("p1")

    assert result["passed"] is True


def test_report_builder_rejects_duplicate_model_sample_rows(tmp_path: Path) -> None:
    manager = ImprovementManager(tmp_path / "improvement")
    results = tmp_path / "results.json"
    write(results, [
        {"sample_id": "s1", "model": "m", "score": 1},
        {"sample_id": "s1", "model": "m", "score": 2},
    ])

    try:
        manager.build_report(results, tmp_path / "report.json", model="m", tests_passed=True)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate results were accepted")
