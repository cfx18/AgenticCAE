"""Replay a frozen CAD campaign through a new verifier without redrawing artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import time
from typing import Any

from .campaign import build_campaign_manifest, validate_campaign_manifest, write_immutable_manifest
from .isolation import sha256_file
from .metrics import evidence_qualified_completion
from ..paths import project_root
from ..verification.extract_core_console import extract_dwg_core
from ..verification.render_core_console import render_dwg_core
from ..verification.verify import verify_scene
from ..verification.vlm.evaluate import evaluate_visual_gaps
from ..verification.vlm.render_scene import render_scene


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def replay_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    stable = [item for item in results if item.get("new_eqc") is not None]
    old = [float(item["old_eqc"]) for item in stable]
    new = [float(item["new_eqc"]) for item in stable]
    return {
        "jobs": len(results),
        "completed": len(stable),
        "evaluation_incomplete": sum(item.get("status") == "evaluation-incomplete" for item in results),
        "old_mean_eqc": round(statistics.mean(old), 2) if old else None,
        "new_mean_eqc": round(statistics.mean(new), 2) if new else None,
        "mean_delta": round(statistics.mean(new) - statistics.mean(old), 2) if old else None,
        "old_passed": sum(float(item["old_eqc"]) >= 100 for item in stable),
        "new_passed": sum(float(item["new_eqc"]) >= 100 for item in stable),
        "improved": sum(float(item["new_eqc"]) > float(item["old_eqc"]) for item in stable),
        "regressed": sum(float(item["new_eqc"]) < float(item["old_eqc"]) for item in stable),
    }


def _source_paths(workspace: Path) -> list[Path]:
    return [
        workspace / "src/cad_evoloop/verification/verify.py",
        workspace / "src/cad_evoloop/verification/extract_core_console.py",
        workspace / "src/cad_evoloop/verification/render_core_console.py",
        workspace / "src/cad_evoloop/verification/vlm/evaluate.py",
        workspace / "src/cad_evoloop/verification/vlm/provider.py",
        workspace / "src/cad_evoloop/verification/vlm/render_scene.py",
        workspace / "src/cad_evoloop/evaluation/metrics.py",
        Path(__file__).resolve(),
    ]


def replay_verifier(
    baseline_campaign: Path,
    output_dir: Path,
    *,
    campaign_id: str,
    vlm_model: str = "gpt-5.5",
    confidence_threshold: float = 0.85,
    max_jobs: int | None = None,
) -> dict[str, Any]:
    baseline_campaign = Path(baseline_campaign).resolve()
    output_dir = Path(output_dir).resolve()
    workspace = project_root()
    eval_root = baseline_campaign.parents[1]
    baseline_manifest = json.loads(
        (baseline_campaign / "campaign-manifest.json").read_text(encoding="utf-8")
    )
    validate_campaign_manifest(baseline_manifest)
    baseline_results = json.loads((baseline_campaign / "results.json").read_text(encoding="utf-8"))
    if max_jobs is not None:
        baseline_results = baseline_results[:max_jobs]
    jobs = [
        {"sample_id": item["sample_id"], "model": item["model"]}
        for item in baseline_results
    ]
    manifest = build_campaign_manifest(
        campaign_id=campaign_id,
        mode="pilot",
        eval_root=eval_root,
        sample_ids=list(dict.fromkeys(item["sample_id"] for item in baseline_results)),
        models=[
            {"name": name, "reasoning_effort": "verifier-only"}
            for name in dict.fromkeys(item["model"] for item in baseline_results)
        ],
        source_paths=_source_paths(workspace),
        execution={
            "type": "verifier-replay",
            "baseline_campaign_id": baseline_manifest["campaign_id"],
            "baseline_manifest_sha256": baseline_manifest["manifest_sha256"],
            "vlm_model": vlm_model,
            "confidence_threshold": confidence_threshold,
            "jobs": jobs,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_immutable_manifest(output_dir / "campaign-manifest.json", manifest)
    results_path = output_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    completed = {(item["sample_id"], item["model"]) for item in results}
    for baseline in baseline_results:
        key = (baseline["sample_id"], baseline["model"])
        if key in completed:
            continue
        started = time.perf_counter()
        sample_dir = eval_root / "samples" / baseline["sample_id"]
        baseline_job = Path(baseline["job_dir"]).resolve()
        job_dir = output_dir / baseline["sample_id"] / baseline["model"].replace(".", "-")
        job_dir.mkdir(parents=True, exist_ok=True)
        candidate = baseline_job / "candidate.dwg"
        scene_path = job_dir / "scene.json"
        deterministic_path = job_dir / "deterministic-verdict.json"
        render_path = job_dir / "candidate-native.png"
        visual_path = job_dir / "visual-verdict.json"
        final_path = job_dir / "verdict.json"
        errors: list[str] = []
        visual = None
        try:
            scene = extract_dwg_core(candidate)
            scene_path.write_text(json.dumps(scene, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            task = json.loads((sample_dir / "task_desc.json").read_text(encoding="utf-8"))
            rubrics = json.loads((sample_dir / "rubrics.json").read_text(encoding="utf-8"))
            deterministic = verify_scene(task, rubrics, scene)
            deterministic_path.write_text(
                json.dumps(deterministic, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            try:
                render_dwg_core(candidate, render_path)
            except Exception as exc:
                errors.append(f"native-render: {exc!r}")
                render_scene(scene, render_path)
            unverified = [
                item for item in deterministic.get("rubrics", [])
                if item.get("status") == "unverified"
            ]
            references = [
                path for path in sorted((baseline_job / "input_files").glob("*"))
                if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
            ]
            if unverified:
                visual = evaluate_visual_gaps(
                    sample_dir=sample_dir,
                    deterministic_path=deterministic_path,
                    candidate_images=[render_path],
                    reference_images=references,
                    output=visual_path,
                    work_dir=job_dir / "vlm-work",
                    model=vlm_model,
                    confidence_threshold=confidence_threshold,
                )
            eqc = evidence_qualified_completion(deterministic, visual)
            verdict = {**deterministic, "visual_evidence": visual, "eqc": eqc}
            final_path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            status = "passed" if eqc["success"] else "failed"
            new_eqc = eqc["eqc"]
            coverage = eqc["coverage"]
        except Exception as exc:
            errors.append(repr(exc))
            status = "evaluation-incomplete"
            new_eqc = None
            coverage = None
        artifacts = {}
        for path in (scene_path, deterministic_path, render_path, visual_path, final_path):
            if path.is_file():
                artifacts[path.name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        row = {
            "sample_id": baseline["sample_id"],
            "model": baseline["model"],
            "status": status,
            "old_eqc": baseline.get("eqc", 0),
            "new_eqc": new_eqc,
            "delta": None if new_eqc is None else round(float(new_eqc) - float(baseline.get("eqc", 0)), 2),
            "coverage": coverage,
            "candidate_sha256": sha256_file(candidate),
            "baseline_run_id": baseline.get("run_id"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "errors": errors,
            "artifacts": artifacts,
            "job_dir": str(job_dir),
        }
        results.append(row)
        results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False))
    summary = replay_summary(results)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"manifest_sha256": manifest["manifest_sha256"], **summary}

