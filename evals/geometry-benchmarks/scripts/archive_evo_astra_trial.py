"""Archive this completed trial's staged models and interrupted execution evidence."""

import json
from pathlib import Path

from cad_evoloop.ledger.ledger import RunLedger, sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root


def main():
    root = project_root()
    campaign = root / "evals/geometry-benchmarks/batch/evocad-astra-ultra-omnimech2-https-20260915"
    record = json.loads((campaign / "trial-config.json").read_text(encoding="utf-8"))
    if record["state"] != "completed":
        raise ValueError("Trial must be complete before archival")
    job = campaign / "omnimech-2/gpt-6-astra"
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    run = Path(result["ledger_run"])
    ledger = RunLedger(root / "evals/geometry-benchmarks")
    for name in ("candidate.dwg", "candidate.a001.dwg"):
        if sha256_file(job / name) != result["candidate_sha256"]:
            raise ValueError(f"Scored candidate changed: {name}")
    audit_path = campaign / "postrun-integrity.json"
    if audit_path.exists():
        raise ValueError("Postrun archival already exists")

    sources = {}

    def include(path, role):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Archive source escapes workspace: {path}")
        if path.is_file():
            sources[path] = role

    for path in job.glob("stage*.dwg"):
        include(path, "agent-stage-" + path.stem.replace("_", "-"))
    interruptions = job / "attempts/a001/action-interruptions"
    for path in interruptions.rglob("*"):
        if path.is_file():
            include(path, "interrupted-action-" + path.parent.name)
    for path in (campaign / "supervisor-recovery").glob("*"):
        include(path, "supervisor-recovery")
    for name in ("trial-config.json", "selection.json", "agent-campaign-manifest.json",
                 "agent-results.json", "agent-plan.json", "report-materialization.json"):
        include(campaign / name, "experiment-registration")
    for name in ("evo_astra_omnimech2_trial.py", "resume_evo_astra_trial.py",
                 "archive_evo_astra_trial.py"):
        include(Path(__file__).parent / name, "experiment-supervisor-source")

    # Audit responses bind the native job directories; no model-authored paths are executed.
    native_jobs = set()
    for audit in (job / "attempts/a001").rglob("mcp-audit.jsonl"):
        for line in audit.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            for block in event.get("response", {}).get("result", {}).get("content", []):
                if block.get("type") != "text":
                    continue
                try:
                    payload = json.loads(block["text"])
                except (ValueError, KeyError):
                    continue
                if isinstance(payload, dict) and payload.get("job_dir"):
                    directory = Path(payload["job_dir"]).resolve()
                    if not directory.is_relative_to(root / "mcp/jobs"):
                        raise ValueError(f"Native job directory outside workspace jobs: {directory}")
                    native_jobs.add(directory)
    for directory in sorted(native_jobs):
        for path in directory.rglob("*"):
            if path.is_file():
                include(path, "native-job-" + directory.name)

    for path, role in sorted(sources.items()):
        ledger.add_artifact(run, "a001", path, role=role)
    ledger.event(
        run, "experiment.postrun_archived",
        "Preserved staged geometry, interrupted conversation, supervisor recovery and native jobs",
        actor="system", attempt_id="a001",
        payload={"extra_artifacts": len(sources), "native_jobs": len(native_jobs),
                 "supervisor_interruptions": 1, "manual_geometry_feedback": False,
                 "first_score": result["attempts"][0]["score"],
                 "selected_score": result["score"],
                 "timing_caveat": "Recovery resets the runner wall clock; interrupted time is additional",
                 "usage_caveat": "Resumed CLI usage may be cumulative; reported sums are not validated billable usage"},
    )
    integrity = ledger.verify_integrity(run)
    write_json_atomic(audit_path, {
        "created_at": utc_now(), "extra_artifacts": len(sources),
        "native_jobs": len(native_jobs), "candidate_sha256": result["candidate_sha256"],
        "integrity": integrity,
    })
    print(json.dumps(json.loads(audit_path.read_text(encoding="utf-8"))))
    if not integrity["ok"]:
        raise ValueError("Postrun ledger integrity failed")


if __name__ == "__main__":
    main()
