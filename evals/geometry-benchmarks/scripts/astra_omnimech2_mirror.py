"""Reproduce the human-requested OmniMech 2 mirror repair in native AutoCAD."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import time

from cad_evoloop.backends.autocad.core_console import CoreConsoleJobManager, TERMINAL_STATES
from cad_evoloop.backends.autocad.topology import export_topology_core
from cad_evoloop.evaluation.geometry_campaign import geometry_verdict
from cad_evoloop.evaluation.geometry_review import generate_geometry_review_bundle
from cad_evoloop.evaluation.geometry_score import score_geometry_files
from cad_evoloop.ledger import RunLedger
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root
from cad_evoloop.verification.export_core_console import export_dwg_core
from cad_evoloop.verification.extract_core_console import CORE_CONSOLE


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = project_root()
    source_campaign = root / "evals/geometry-benchmarks/batch/direct-codex-astra-ultra-omnimech2-https-20260914"
    source_job = source_campaign / "omnimech-2/gpt-6-astra"
    source_dwg = source_job / "candidate.a001.dwg"
    diagnostic = root / "evals/geometry-benchmarks/diagnostics/astra-omnimech2-mirror-20260914"
    campaign_id = "human-mirror-astra-omnimech2-20260914"
    campaign = root / "evals/geometry-benchmarks/batch" / campaign_id
    job_dir = campaign / "omnimech-2/astra-human-mirror-y"
    attempt = job_dir / "attempts/a001"
    review = root / "reports/generated" / f"{campaign_id}-review"
    source_manifest = root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    gt = source_manifest.parent / "omnimech/2/ground_truth.step"
    source_result = read_json(source_campaign / "results.json")[0]
    protected = [source_dwg, source_campaign / "results.json", gt,
                 source_job / "attempts/a001/geometry-verdict.json"]
    hashes = {str(path): sha256_file(path) for path in protected}
    campaign.mkdir(parents=True, exist_ok=False)
    if review.exists():
        raise FileExistsError(review)
    attempt.mkdir(parents=True)
    shutil.copytree(source_job / "input_files", job_dir / "input_files")
    task = read_json(source_job / "task.json")
    task["task"] = "Human-requested post-hoc mirror diagnostic of Astra's original output. " + task["task"]
    write_json_atomic(job_dir / "task.json", task)
    provenance = {
        "created_at": utc_now(), "eligible_for_original_agent_score": False,
        "type": "human-requested-gt-assisted-posthoc-mirror",
        "parent_run_id": source_result["run_id"],
        "source_hashes": hashes, "mesh_diagnostic_sha256": sha256_file(diagnostic / "diagnostic.json"),
        "transform": {"frame": "original-DWG-WCS", "plane": "y=32", "map": "(x,y,z) -> (x,64-y,z)"},
        "changes": "Reflect the complete solid. No feature edits, rescaling or threshold changes.",
        "agent_model_calls": 0,
    }
    write_json_atomic(campaign / "provenance.json", provenance)
    ledger = RunLedger(root / "evals/geometry-benchmarks")
    run_dir = ledger.start(
        "omnimech-2", run_id=campaign_id, parent_run_id=source_result["run_id"],
        agent={"system": "human-guided-posthoc-diagnostic", "model_calls": 0},
        source_paths=[Path(__file__), root / "src/cad_evoloop/evaluation/geometry_score.py"],
        input_paths=[source_dwg, campaign / "provenance.json"],
    )
    attempt_id = ledger.add_attempt(run_dir, label="human-requested-y-mirror-not-agent-reflection")
    lisp = '''(setvar "FILEDIA" 0)
(setvar "CMDECHO" 1)
(setvar "OSMODE" 0)
(command "_.UCS" "_World")
(setq mirror-solids (ssget "_X" '((0 . "3DSOLID") (410 . "Model"))))
(if (/= (sslength mirror-solids) 1) (exit))
(command "_.MIRROR3D" mirror-solids "" "_ZX" '(0.0 32.0 0.0) "_Yes")
(setq mirror-final (ssget "_X" '((0 . "3DSOLID") (410 . "Model"))))
(if (/= (sslength mirror-final) 1) (exit))
(princ)
'''
    candidate = job_dir / "candidate.a001.dwg"
    manager = CoreConsoleJobManager(root, CORE_CONSOLE, source_dwg)
    started = time.monotonic()
    job = manager.start(lisp, str(candidate), str(source_dwg), timeout=180, capture_boolean_lineage=False)
    try:
        while job["status"] not in TERMINAL_STATES:
            time.sleep(0.5)
            job = manager.status(job["job_id"])
    finally:
        if job["status"] not in TERMINAL_STATES:
            manager.cancel(job["job_id"])
    write_json_atomic(attempt / "mirror-core-job.json", job)
    if job["status"] != "succeeded":
        raise RuntimeError(job)
    print("Native mirror saved", flush=True)
    topology_job = export_topology_core(
        root, candidate, attempt / "candidate-topology.json", executable=CORE_CONSOLE,
        plugin=root / ".local/autocad-topology/EvoCadTopology.dll", timeout=180,
    )
    write_json_atomic(attempt / "topology-core-job.json", topology_job)
    export_dwg_core(candidate, attempt / "candidate.stl", timeout=180)
    scored = score_geometry_files(attempt / "candidate.stl", gt, sample_count=20000, voxel_resolution=64,
                                  candidate_topology_path=attempt / "candidate-topology.json")
    verdict = geometry_verdict(scored, "omnimech:2")
    write_json_atomic(attempt / "geometry-verdict.json", verdict)
    print(json.dumps({"score": verdict["score"], "passed": verdict["passed"], "metrics": verdict["metrics"]}), flush=True)
    provenance["source_integrity_verified"] = all(sha256_file(Path(p)) == h for p, h in hashes.items())
    if not provenance["source_integrity_verified"]:
        raise RuntimeError("Protected source changed")
    write_json_atomic(campaign / "provenance.json", provenance)
    for path in [candidate, campaign / "provenance.json", *attempt.glob("*"), *Path(job["job_dir"]).glob("*")]:
        if path.is_file():
            ledger.add_artifact(run_dir, attempt_id, path, role="mirror-diagnostic")
    ledger.finish(run_dir, attempt_id, attempt / "geometry-verdict.json")
    integrity = ledger.verify_integrity(run_dir)
    if not integrity["ok"]:
        raise RuntimeError(integrity)
    result = {
        "schema_version": "1.0", "protocol": scored["protocol"], "campaign": campaign_id,
        "agent_loop_protocol": "human-guided-posthoc-mirror-v1", "sample_id": "omnimech:2",
        "run_id": campaign_id, "model": "astra-human-mirror-y", "reasoning_effort": None,
        "status": "passed" if verdict["passed"] else "failed", "score": verdict["score"],
        "passed": verdict["passed"], "selected_attempt_id": "a001",
        "stop_reason": "human-requested-diagnostic-complete", "eligible_for_original_agent_score": False,
        "candidate_sha256": sha256_file(candidate), "ground_truth_sha256": sha256_file(gt),
        "job_dir": str(job_dir), "ledger_run": str(run_dir), "integrity": integrity,
        "attempts": [{"attempt_id": "a001", "attempt_number": 1, "score": verdict["score"],
                      "passed": verdict["passed"], "elapsed_seconds": round(time.monotonic() - started, 3),
                      "verdict": str(attempt / "geometry-verdict.json"), "errors": [],
                      "decision_reason": "Human identified a mirror relation; no new agent call.",
                      "thread_id": None, "usage": None}],
    }
    write_json_atomic(job_dir / "result.json", result)
    # Include the unchanged original beside the derivative for review; do not rerun it.
    write_json_atomic(campaign / "results.json", [source_result, result])
    write_json_atomic(campaign / "campaign-manifest.json", {
        "schema_version": "1.0", "campaign_id": campaign_id, "protocol": scored["protocol"],
        "agent_loop_protocol": "human-guided-posthoc-mirror-v1",
        "source_manifest_sha256": sha256_file(source_manifest), "sample_ids": ["omnimech:2"],
        "models": [{"name": "gpt-6-astra", "model": "gpt-6-astra"},
                   {"name": "astra-human-mirror-y", "model": "astra-human-mirror-y"}],
        "execution": provenance,
    })
    bundle = generate_geometry_review_bundle(campaign, review, source_manifest=source_manifest, render_geometry=True)
    print(json.dumps({"review": str(review), "bundle_sha256": bundle["bundle_sha256"], "integrity": integrity}), flush=True)


if __name__ == "__main__":
    main()
