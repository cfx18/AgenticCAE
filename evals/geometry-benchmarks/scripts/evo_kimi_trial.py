"""Run the registered three-case EvoCAD/Kimi trial without an LLM supervisor."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from cad_evoloop.agent.models.kimi_geometry import KimiGeometryTransport
from cad_evoloop.evaluation.agent_geometry_campaign import _canonical_hash, run_agent_geometry_campaign
from cad_evoloop.evaluation.geometry_review import generate_geometry_review_bundle
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root

sys.path.insert(0, str(project_root() / "evals/Paper_filmcooling/scripts"))
from run_paper_kimi import find_kimi_invocation, parse_dotenv, validate_kimi_env

CAMPAIGN = "evocad-kimi-k3-omnimech-2-4-10-20260916"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    root = project_root()
    directory = root / "evals/geometry-benchmarks/batch" / CAMPAIGN
    manifest = root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    values = parse_dotenv(root / "evals/Paper_filmcooling/kimi/.env")
    validate_kimi_env(values)
    transport = KimiGeometryTransport(
        workspace=root, invocation=find_kimi_invocation(root, None), environment=values,
        autocad_python=Path("E:/python/python.exe"),
    )
    if args.smoke_test:
        smoke = root / ".local/kimi-evocad-smoke"
        smoke.mkdir(exist_ok=False)
        first = smoke / "first"
        first.mkdir()
        command = transport.start_command(
            "unused", "kimi-k3", "max", smoke, [],
            "Remember the string CADTRANSPORT73 for my next message. Reply READY only. Do not use tools.",
            first / "mcp-audit.jsonl", first / "final.txt",
        )
        code, timed_out = transport.run_process(command, cwd=smoke, events_path=first / "kimi-events.jsonl",
                                                stderr_path=first / "stderr.log", timeout=180)
        if code != 0 or timed_out:
            raise RuntimeError("First smoke-test turn failed")
        session = transport.read_events(first / "kimi-events.jsonl")["thread_id"]
        if not session:
            raise RuntimeError("Smoke-test conversation ID unavailable")
        second = smoke / "second"
        second.mkdir()
        schema_path = second / "schema.json"
        write_json_atomic(schema_path, {"type": "object", "required": ["remembered"],
                                       "properties": {"remembered": {"type": "string"}},
                                       "additionalProperties": False})
        command = transport.resume_command(
            "unused", "kimi-k3", "max", smoke, session,
            "Return the string I asked you to remember as the remembered field. Do not use tools.",
            second / "reflection.json", with_autocad=False, output_schema=schema_path,
        )
        code, timed_out = transport.run_process(command, cwd=smoke, events_path=second / "kimi-events.jsonl",
                                                stderr_path=second / "stderr.log", timeout=180)
        value = json.loads((second / "reflection.json").read_text(encoding="utf-8"))
        if code != 0 or timed_out or value != {"remembered": "CADTRANSPORT73"}:
            raise RuntimeError("Kimi session resume/schema smoke test failed")
        print(json.dumps({"state": "smoke_passed", "session_id": session, "value": value}), flush=True)
        return
    config = dict(campaign=CAMPAIGN, model="kimi-k3", effort="max",
                  executable=transport.invocation[0], timeout=5400, max_iterations=12,
                  stagnation_limit=2, job_time_budget=5400, score_samples=20000,
                  voxel_resolution=64, reconstruction_mode="baseline", max_jobs=1)
    selection_path = directory / "selection.json"
    record_path = directory / "trial-config.json"
    if args.prepare_only:
        directory.mkdir(parents=True, exist_ok=False)
        split = root / "evals/geometry-benchmarks/splits/geometry-50-split-v1.json"
        selection = {
            "schema_version": "1.0", "kind": "frozen-agent-evaluation-selection",
            "source_split": Path(os.path.relpath(split, directory)).as_posix(),
            "source_split_sha256": sha256_file(split),
            "source_manifest_sha256": sha256_file(manifest),
            "selection_strategy": "User-requested EvoCAD/Kimi comparison on the same three drawings",
            "sample_count": 3, "sample_ids": ["omnimech:2", "omnimech:4", "omnimech:10"],
        }
        selection["selection_sha256"] = _canonical_hash(selection, "selection_sha256")
        write_json_atomic(selection_path, selection)
        write_json_atomic(record_path, {
            "state": "prepared", "created_at": utc_now(), "config": config,
            "runner_sha256": sha256_file(Path(__file__)),
            "harness": "EvoCAD durable kernel and geometry loop; Kimi Code action executor",
            "gt_metric_feedback": True, "gt_geometry_input": False,
            "forced_ir": False, "human_review_input": False, "manual_geometry_hint": False,
            "native_control_job_budget_seconds": 5400,
            "prior_astra_evo_job_budget_seconds": 3600,
            "usage_note": "Kimi stream does not expose token usage; empty usage is unavailable, not zero",
        })
        result = run_agent_geometry_campaign(manifest, selection_path, **config,
                                             transport=transport, dry_run=True)
        print(json.dumps({"state": "prepared", "jobs": result["jobs"]}), flush=True)
        return
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["state"] != "prepared" or record["config"] != config:
        raise ValueError("Only a matching, unstarted prepared trial may launch")
    if record["runner_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("Prepared runner changed")
    record.update(state="running", started_at=utc_now(), pid=os.getpid(), completed=[])
    write_json_atomic(record_path, record)
    try:
        for number in (2, 4, 10):
            record.update(current_sample=f"omnimech:{number}", stage="evaluating")
            write_json_atomic(record_path, record)
            print(f"START omnimech:{number}", flush=True)
            run_agent_geometry_campaign(manifest, selection_path, **config, transport=transport)
            result_path = directory / f"omnimech-{number}/kimi-k3/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            record["completed"].append({
                "sample_id": result["sample_id"], "score": result["score"],
                "passed": result["passed"], "stop_reason": result["stop_reason"],
                "attempt_count": len(result["attempts"]), "result": str(result_path),
            })
            record.update(stage="exporting_review")
            write_json_atomic(record_path, record)
            print(json.dumps(record["completed"][-1]), flush=True)
            export_dir = directory / f"review-source-{number}"
            export_dir.mkdir()
            write_json_atomic(export_dir / "results.json", [result])
            write_json_atomic(export_dir / "campaign-manifest.json", {
                "schema_version": "1.0", "campaign_id": CAMPAIGN,
                "source_manifest_sha256": sha256_file(manifest),
                "agent_loop_protocol": result["agent_loop_protocol"],
                "protocol": result["protocol"], "sample_ids": [result["sample_id"]],
                "models": [{"name": "kimi-k3", "model": "kimi-k3"}], "reasoning_effort": "max",
            })
            bundle_relative = f"reports/generated/{CAMPAIGN}-{number}-review"
            generate_geometry_review_bundle(export_dir, root / bundle_relative,
                                            source_manifest=manifest, render_geometry=True)
            catalog_path = root / "apps/geometry-review/catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            key = f"evocad-kimi-{number}"
            if any(item["id"] == key for item in catalog["bundles"]):
                raise ValueError(f"Refusing to replace catalog entry {key}")
            catalog["bundles"].insert(0, {
                "id": key, "harness": "EvoCAD", "label": f"OmniMech {number} - Kimi K3 (feedback loop)",
                "bundle": bundle_relative,
                "reviews": f"evals/geometry-benchmarks/human-reviews/{CAMPAIGN}-{number}.jsonl",
            })
            write_json_atomic(catalog_path, catalog)
            # A regular subprocess refreshes the frozen catalog; no model is polled.
            refresh = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(root / "evals/geometry-benchmarks/scripts/refresh-kimi-review.ps1"),
            ], cwd=root, capture_output=True, text=True, timeout=180)
            (directory / f"review-refresh-{number}.log").write_text(
                refresh.stdout + refresh.stderr, encoding="utf-8")
            record["completed"][-1]["review_url"] = f"http://127.0.0.1:8770/?view={key}"
            record["completed"][-1]["review_server_refreshed"] = refresh.returncode == 0
            write_json_atomic(record_path, record)
        record.update(state="completed", stage="finished", finished_at=utc_now())
    except Exception as exc:
        record.update(state="execution_error", error=repr(exc), finished_at=utc_now())
        traceback.print_exc()
        raise
    finally:
        write_json_atomic(record_path, record)


if __name__ == "__main__":
    main()
