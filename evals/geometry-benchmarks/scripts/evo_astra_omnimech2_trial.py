"""Registered EvoCAD/Astra Ultra trial with scoped HTTPS transport overrides."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

from cad_evoloop.evaluation import geometry_campaign
from cad_evoloop.evaluation.agent_geometry_campaign import _canonical_hash, run_agent_geometry_campaign
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root


HTTPS_OVERRIDES = (
    'model_provider="evocad_openai_https"',
    'model_providers.evocad_openai_https={name="OpenAI HTTPS",'
    'base_url="https://chatgpt.com/backend-api/codex",wire_api="responses",'
    'requires_openai_auth=true,supports_websockets=false}',
)


def with_https(builder):
    def build(**kwargs):
        kwargs["config_overrides"] = (*kwargs.get("config_overrides", ()), *HTTPS_OVERRIDES)
        return builder(**kwargs)
    return build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    root = project_root()
    campaign = "evocad-astra-ultra-omnimech2-https-20260915"
    directory = root / "evals/geometry-benchmarks/batch" / campaign
    selection_path = directory / "selection.json"
    record_path = directory / "trial-config.json"
    executable = "C:/Users/8320/AppData/Local/OpenAI/Codex/bin/bffc5354119c8421/codex.exe"
    config = {
        "campaign": campaign, "model": "gpt-6-astra", "effort": "ultra",
        "executable": executable, "timeout": 1800, "max_iterations": 12,
        "stagnation_limit": 2, "job_time_budget": 3600,
        "score_samples": 20000, "voxel_resolution": 64,
        "reconstruction_mode": "baseline", "max_jobs": 1,
    }
    manifest = root / ".local/datasets/evocad/materialized/geometry-50-v1/manifest.json"
    if args.prepare_only:
        directory.mkdir(parents=True, exist_ok=False)
        source_split = root / "evals/geometry-benchmarks/splits/geometry-50-split-v1.json"
        selection = {
            "schema_version": "1.0", "kind": "frozen-agent-evaluation-selection",
            "source_split": Path(os.path.relpath(source_split, directory)).as_posix(),
            "source_split_sha256": sha256_file(source_split),
            "source_manifest_sha256": sha256_file(manifest),
            "selection_strategy": "User-requested single OmniMech 2 harness trial",
            "sample_count": 1, "sample_ids": ["omnimech:2"],
        }
        selection["selection_sha256"] = _canonical_hash(selection, "selection_sha256")
        write_json_atomic(selection_path, selection)
        record = {
            "state": "prepared", "created_at": utc_now(), "config": config,
            "runner_sha256": sha256_file(Path(__file__)),
            "transport_overrides": HTTPS_OVERRIDES,
            "harness": "EvoCAD durable kernel with geometry feedback loop",
            "manual_mirror_hint": False, "human_review_input": False, "oracle_input": False,
            "gt_metric_feedback": True, "frozen_gt_geometry_input": False,
        }
        write_json_atomic(record_path, record)
        result = run_agent_geometry_campaign(manifest, selection_path, **config, dry_run=True)
        print(json.dumps({"state": "prepared", "jobs": result["jobs"], "config": config}), flush=True)
        return
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["state"] != "prepared" or record["config"] != config:
        raise ValueError("Only an unstarted, matching prepared trial may execute")
    if record["runner_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("Prepared experiment runner changed")
    record.update(state="running", started_at=utc_now())
    write_json_atomic(record_path, record)
    # Apply transport to both fresh action and resumed feedback commands only in
    # this process. The existing EvoCAD loop/executor/decision code is unchanged.
    builder = geometry_campaign.build_codex_exec_command
    try:
        with patch.object(geometry_campaign, "build_codex_exec_command", with_https(builder)):
            result = run_agent_geometry_campaign(manifest, selection_path, **config)
    except Exception as exc:
        record.update(state="execution_error", error=repr(exc), finished_at=utc_now())
        write_json_atomic(record_path, record)
        raise
    record.update(state="completed", finished_at=utc_now(), result=result)
    write_json_atomic(record_path, record)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
