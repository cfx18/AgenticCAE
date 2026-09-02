"""Stable command-line entry points for CAD-EvoLoop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sys
from typing import Callable

from .evaluation.campaign import validate_campaign_manifest
from .evaluation.metrics import main as metrics_main
from .evaluation.report import generate_campaign_report
from .evaluation.explorer import generate_explorer_bundle
from .evaluation.replay import replay_verifier
from .evaluation.geometry_dataset import materialize_geometry_pilot
from .evaluation.geometry_score import calibrate_geometry_manifest, score_geometry_files
from .evaluation.geometry_campaign import run_geometry_campaign
from .evaluation.agent_geometry_campaign import run_agent_geometry_campaign
from .evaluation.geometry_report import generate_geometry_campaign_report
from .evaluation.geometry_review import generate_geometry_review_bundle
from .evaluation.geometry_feature_backfill import backfill_geometry_features
from .evaluation.agent_geometry_report import generate_agent_geometry_report
from .evaluation.geometry_split import write_geometry_split
from .evaluation.human_review import HumanReviewStore, serve_geometry_review
from .evaluation.review_feedback import (
    ingest_human_reviews,
    submit_human_clarification,
)
from .paths import project_root
from .verification.export_core_console import export_dwg_core


def _run_script(relative: str) -> None:
    runpy.run_path(str(project_root() / relative), run_name="__main__")


def batch() -> None:
    _run_script("evals/cad-1000-hours/scripts/batch_codex.py")


def ledger() -> None:
    _run_script("evals/cad-1000-hours/scripts/run_ledger.py")


def improve() -> None:
    _run_script("evals/cad-1000-hours/scripts/system_improve.py")


def eqc() -> None:
    metrics_main()


def _verify_campaign() -> None:
    parser = argparse.ArgumentParser(description="Validate an immutable campaign manifest")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    value = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_campaign_manifest(value)
    print(json.dumps({"valid": True, "manifest_sha256": value["manifest_sha256"]}))


def _report_campaign() -> None:
    parser = argparse.ArgumentParser(description="Generate an auditable campaign report")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = generate_campaign_report(args.campaign_dir, args.output)
    print(json.dumps(summary, ensure_ascii=False))


def _export_explorer() -> None:
    parser = argparse.ArgumentParser(description="Export cached evidence for the Run Explorer")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render-native", action="store_true")
    args = parser.parse_args()
    payload = generate_explorer_bundle(
        args.campaign_dir, args.output, render_native=args.render_native,
    )
    print(json.dumps({
        "campaign_id": payload["campaign"]["campaign_id"],
        "runs": len(payload["runs"]),
        "output": str((args.output / "explorer-data.json").resolve()),
    }, ensure_ascii=False))


def _replay_verifier() -> None:
    parser = argparse.ArgumentParser(description="Replay cached DWGs through a verifier profile")
    parser.add_argument("baseline_campaign", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--vlm-model", default="gpt-5.5")
    parser.add_argument("--vlm-confidence", type=float, default=0.85)
    parser.add_argument("--vlm-max-evaluations", type=int, default=3)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--sample", action="append", dest="samples")
    parser.add_argument("--model", action="append", dest="models")
    args = parser.parse_args()
    summary = replay_verifier(
        args.baseline_campaign,
        args.output,
        campaign_id=args.campaign,
        vlm_model=args.vlm_model,
        confidence_threshold=args.vlm_confidence,
        max_evaluations=args.vlm_max_evaluations,
        max_jobs=args.max_jobs,
        sample_ids=set(args.samples) if args.samples else None,
        models=set(args.models) if args.models else None,
    )
    print(json.dumps(summary, ensure_ascii=False))


def _materialize_geometry() -> None:
    parser = argparse.ArgumentParser(description="Materialize a geometry-grounded pilot split")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bench-count", type=int, default=10)
    parser.add_argument("--ortho-count", type=int, default=10)
    parser.add_argument("--omni-count", type=int, default=10)
    args = parser.parse_args()
    payload = materialize_geometry_pilot(
        data_root=args.data_root,
        output_root=args.output,
        bench_count=args.bench_count,
        ortho_count=args.ortho_count,
        omni_count=args.omni_count,
    )
    print(json.dumps({
        "samples": len(payload["samples"]),
        "manifest": payload["manifest_path"],
    }, ensure_ascii=False))


def _score_geometry() -> None:
    parser = argparse.ArgumentParser(description="Score candidate geometry against CAD ground truth")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--voxel-resolution", type=int, default=64)
    args = parser.parse_args()
    result = score_geometry_files(
        args.candidate,
        args.ground_truth,
        sample_count=args.samples,
        voxel_resolution=args.voxel_resolution,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def _calibrate_geometry() -> None:
    parser = argparse.ArgumentParser(description="Calibrate STEP/STL ground-truth consistency")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--voxel-resolution", type=int, default=48)
    args = parser.parse_args()
    result = calibrate_geometry_manifest(
        args.manifest,
        args.output,
        sample_count=args.samples,
        voxel_resolution=args.voxel_resolution,
    )
    print(json.dumps(result["summary"], ensure_ascii=False))


def _export_geometry() -> None:
    parser = argparse.ArgumentParser(description="Export DWG solids to a verifier-ready STL")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--facet-resolution", type=float, default=10.0)
    args = parser.parse_args()
    output = export_dwg_core(
        args.candidate,
        args.output,
        args.timeout,
        facet_resolution=args.facet_resolution,
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))


def _batch_geometry() -> None:
    parser = argparse.ArgumentParser(description="Run a geometry-grounded Codex/AutoCAD campaign")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--sample", action="append", dest="samples")
    parser.add_argument("--split-file", type=Path)
    parser.add_argument(
        "--split-name",
        choices=("dev", "validation", "hidden_test", "cost_pilot"),
    )
    parser.add_argument(
        "--reasoning-effort", default="medium",
        choices=("low", "medium", "high", "xhigh", "max"),
    )
    parser.add_argument(
        "--max-iterations", "--max-attempts", dest="max_iterations", type=int, default=12,
        help="safety ceiling; every iteration still ends with an agent feedback decision",
    )
    parser.add_argument("--stagnation-limit", type=int, default=2)
    parser.add_argument("--job-time-budget", type=int, default=3600)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--score-samples", type=int, default=20000)
    parser.add_argument("--voxel-resolution", type=int, default=64)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.samples and args.split_file:
        parser.error("--sample cannot be combined with --split-file")
    if bool(args.split_file) != bool(args.split_name):
        parser.error("--split-file and --split-name must be provided together")
    result = run_geometry_campaign(
        args.manifest,
        campaign=args.campaign,
        models=args.models,
        sample_ids=set(args.samples) if args.samples else None,
        effort=args.reasoning_effort,
        max_iterations=args.max_iterations,
        stagnation_limit=args.stagnation_limit,
        job_time_budget=args.job_time_budget,
        timeout=args.timeout,
        max_jobs=args.max_jobs,
        score_samples=args.score_samples,
        voxel_resolution=args.voxel_resolution,
        dry_run=args.dry_run,
        split_file=args.split_file,
        split_name=args.split_name,
    )
    print(json.dumps(result, ensure_ascii=False))


def _backfill_geometry_features() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill native face localization for frozen selected checkpoints",
    )
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--voxel-resolution", type=int, default=64)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-jobs", type=int)
    args = parser.parse_args()
    result = backfill_geometry_features(
        args.campaign_dir, args.source_manifest, args.output,
        sample_count=args.samples, voxel_resolution=args.voxel_resolution,
        timeout=args.timeout, max_jobs=args.max_jobs,
    )
    print(json.dumps(result, ensure_ascii=False))


def _batch_agent_geometry() -> None:
    parser = argparse.ArgumentParser(description="Run frozen geometry through the durable agent")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--stagnation-limit", type=int, default=2)
    parser.add_argument("--job-time-budget", type=int, default=3600)
    parser.add_argument("--score-samples", type=int, default=20000)
    parser.add_argument("--voxel-resolution", type=int, default=64)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--human-feedback", type=Path)
    parser.add_argument(
        "--feedback-only", action="store_true",
        help="schedule only actionable samples in the bound human feedback manifest",
    )
    args = parser.parse_args()
    result = run_agent_geometry_campaign(
        args.manifest,
        args.selection,
        campaign=args.campaign,
        model=args.model,
        effort=args.reasoning_effort,
        timeout=args.timeout,
        max_iterations=args.max_iterations,
        stagnation_limit=args.stagnation_limit,
        job_time_budget=args.job_time_budget,
        score_samples=args.score_samples,
        voxel_resolution=args.voxel_resolution,
        max_jobs=args.max_jobs,
        dry_run=args.dry_run,
        human_feedback=args.human_feedback,
        feedback_only=args.feedback_only,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _report_geometry() -> None:
    parser = argparse.ArgumentParser(description="Generate a geometry campaign report")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotations", type=Path)
    args = parser.parse_args()
    result = generate_geometry_campaign_report(
        args.campaign_dir, args.output, annotations_path=args.annotations,
    )
    print(json.dumps(result, ensure_ascii=False))


def _report_agent_geometry() -> None:
    parser = argparse.ArgumentParser(description="Generate a durable-agent geometry report")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    result = generate_agent_geometry_report(
        args.campaign_dir, args.output, baseline_dir=args.baseline,
    )
    print(json.dumps(result, ensure_ascii=False))


def _split_geometry() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic geometry benchmark split")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="evocad-geometry-split-v1-20260830")
    parser.add_argument("--pilot-count", type=int, default=10)
    args = parser.parse_args()
    result = write_geometry_split(
        args.manifest,
        args.output,
        seed=args.seed,
        pilot_count=args.pilot_count,
    )
    print(json.dumps({
        "samples": result["sample_count"],
        "split_sha256": result["split_sha256"],
        "output": str(args.output.resolve()),
    }, ensure_ascii=False))


def _export_geometry_review() -> None:
    parser = argparse.ArgumentParser(description="Export a human-reviewable geometry evidence bundle")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--feature-backfill", type=Path)
    parser.add_argument("--render-geometry", action="store_true")
    args = parser.parse_args()
    payload = generate_geometry_review_bundle(
        args.campaign_dir,
        args.output,
        source_manifest=args.source_manifest,
        annotations_path=args.annotations,
        render_geometry=args.render_geometry,
        feature_backfill=args.feature_backfill,
    )
    print(json.dumps({
        "campaign_id": payload["campaign"]["campaign_id"],
        "runs": len(payload["runs"]),
        "bundle_sha256": payload["bundle_sha256"],
        "output": str((args.output / "review-data.json").resolve()),
    }, ensure_ascii=False))


def _serve_geometry_review() -> None:
    parser = argparse.ArgumentParser(description="Serve the geometry review workbench and ledger API")
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    serve_geometry_review(
        args.bundle_dir,
        args.reviews,
        app_dir=args.bundle_dir / "app",
        host=args.host,
        port=args.port,
    )


def _verify_geometry_reviews() -> None:
    parser = argparse.ArgumentParser(description="Verify and summarize a human review ledger")
    parser.add_argument("bundle", type=Path, help="Path to review-data.json")
    parser.add_argument("reviews", type=Path, help="Path to the human review JSONL ledger")
    args = parser.parse_args()
    result = HumanReviewStore(args.bundle, args.reviews).response()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["integrity"]["ok"]:
        raise SystemExit(1)


def _ingest_geometry_reviews() -> None:
    parser = argparse.ArgumentParser(
        description="Compile verified human reviews into Agent feedback artifacts",
    )
    parser.add_argument("bundle", type=Path, help="Path to review-data.json")
    parser.add_argument("reviews", type=Path, help="Path to the review JSONL ledger")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = ingest_human_reviews(args.bundle, args.reviews, args.output)
    print(json.dumps({
        "protocol": result["protocol"],
        "active_reviews": result["active_review_count"],
        "samples": result["sample_count"],
        "feedback_manifest_sha256": result["feedback_manifest_sha256"],
        "output": str(args.output.resolve()),
    }, indent=2, ensure_ascii=False))


def _submit_agent_clarification() -> None:
    parser = argparse.ArgumentParser(
        description="Submit a response to a blocked Agent human-clarification gate",
    )
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("response", type=Path)
    args = parser.parse_args()
    state = submit_human_clarification(args.project_dir, args.response)
    print(json.dumps({
        "project_id": state["project_id"],
        "project_status": state["status"],
        "human_clarification_status": state["work_units"]["human-clarification"]["status"],
    }, indent=2, ensure_ascii=False))


def main() -> None:
    commands: dict[str, tuple[Callable[[], None], str]] = {
        "batch": (batch, "run a model evaluation campaign"),
        "ledger": (ledger, "query the trajectory ledger"),
        "improve": (improve, "manage system improvement proposals"),
        "eqc": (eqc, "compute evidence-qualified completion"),
        "campaign-verify": (_verify_campaign, "validate a campaign manifest"),
        "report": (_report_campaign, "generate campaign tables and paper-ready figures"),
        "explorer-export": (_export_explorer, "export cached trajectories for the Run Explorer"),
        "verifier-replay": (_replay_verifier, "replay cached DWGs without redrawing"),
        "geometry-materialize": (_materialize_geometry, "materialize geometry-grounded samples"),
        "geometry-score": (_score_geometry, "compare candidate and ground-truth geometry"),
        "geometry-calibrate": (_calibrate_geometry, "calibrate STEP/STL ground-truth pairs"),
        "geometry-export": (_export_geometry, "export DWG solids for geometry scoring"),
        "geometry-batch": (_batch_geometry, "run a geometry-grounded agent campaign"),
        "geometry-feature-backfill": (
            _backfill_geometry_features, "backfill native face localization",
        ),
        "agent-geometry-batch": (_batch_agent_geometry, "run geometry through the durable agent"),
        "geometry-report": (_report_geometry, "generate geometry campaign figures and tables"),
        "agent-geometry-report": (
            _report_agent_geometry, "materialize and report durable-agent geometry results",
        ),
        "geometry-split": (_split_geometry, "create a deterministic benchmark split"),
        "geometry-review-export": (_export_geometry_review, "export human-reviewable geometry evidence"),
        "geometry-review-serve": (_serve_geometry_review, "serve the geometry review workbench"),
        "geometry-review-verify": (_verify_geometry_reviews, "verify and summarize human reviews"),
        "geometry-review-ingest": (
            _ingest_geometry_reviews, "compile human reviews into Agent feedback",
        ),
        "agent-clarification-submit": (
            _submit_agent_clarification, "resume a project with human clarification",
        ),
    }
    if len(sys.argv) > 1 and sys.argv[1] in commands:
        command = sys.argv[1]
        remainder = sys.argv[2:]
        sys.argv = [f"cad-evoloop {command}", *remainder]
        commands[command][0]()
        return

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=commands)
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return


if __name__ == "__main__":
    main()
