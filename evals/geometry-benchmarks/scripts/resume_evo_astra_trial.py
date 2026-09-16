"""Resume the interrupted registered trial without discarding its conversation."""

import json
from pathlib import Path
from unittest.mock import patch

from evo_astra_omnimech2_trial import with_https
from cad_evoloop.agent.models.codex_cli import parse_codex_events
from cad_evoloop.evaluation import geometry_campaign
from cad_evoloop.evaluation.agent_geometry_campaign import run_agent_geometry_campaign
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root


def main():
    root = project_root()
    campaign = root / "evals/geometry-benchmarks/batch/evocad-astra-ultra-omnimech2-https-20260915"
    record_path = campaign / "trial-config.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["state"] != "running":
        raise ValueError("Expected the interrupted running trial, not a completed/new trial")
    job = campaign / "omnimech-2/gpt-6-astra"
    recovery_path = job / "recovery-state.json"
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    active = recovery["active_attempt"]
    if active["phase"] != "action_running":
        raise ValueError("This recovery handles an interrupted action only")
    events_path = job / "attempts" / active["attempt_id"] / "codex-events.jsonl"
    events = parse_codex_events(events_path)
    thread_id = events["thread_id"]
    if not thread_id:
        raise ValueError("Cannot recover the existing conversation identity")
    snapshot = campaign / "supervisor-recovery"
    snapshot.mkdir(exist_ok=False)
    write_json_atomic(snapshot / "recovery-state-before.json", recovery)
    write_json_atomic(snapshot / "trial-config-before.json", record)
    recovery.setdefault("runtime", {})["thread_id"] = thread_id
    write_json_atomic(recovery_path, recovery)
    incident = {
        "resumed_at": utc_now(), "actor": "experiment-supervisor", "thread_id": thread_id,
        "reason": "Host tool execution ended during a progress-query interruption; process absence verified",
        "recovery": "Recover durable project and preserve existing native conversation",
        "previous_events_sha256": sha256_file(events_path),
        "resume_script_sha256": sha256_file(Path(__file__)),
        "manual_geometry_feedback": False,
        "timing_caveat": "Existing recovery restarts the per-invocation job clock; interrupted wall time is additional",
    }
    write_json_atomic(snapshot / "incident.json", incident)
    record.setdefault("supervisor_recoveries", []).append(incident)
    write_json_atomic(record_path, record)
    print(json.dumps(incident), flush=True)
    builder = geometry_campaign.build_codex_exec_command
    try:
        with patch.object(geometry_campaign, "build_codex_exec_command", with_https(builder)):
            result = run_agent_geometry_campaign(
                root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json",
                campaign / "selection.json", **record["config"],
            )
    except Exception as exc:
        record.update(state="execution_error", error=repr(exc), finished_at=utc_now())
        write_json_atomic(record_path, record)
        raise
    record.update(state="completed", finished_at=utc_now(), result=result)
    write_json_atomic(record_path, record)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
