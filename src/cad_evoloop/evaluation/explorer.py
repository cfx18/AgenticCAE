"""Export cached campaign trajectories and evidence for the local Run Explorer."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .campaign import validate_campaign_manifest
from .report import summarize_campaign
from ..verification.render_core_console import render_dwg_core, scene_has_3d


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _workspace_url(path: Path, workspace: Path) -> str:
    return "/" + path.resolve().relative_to(workspace.resolve()).as_posix()


def _evaluation_root(campaign_dir: Path) -> Path:
    for path in (campaign_dir, *campaign_dir.parents):
        if (path / "manifest.json").is_file() and (path / "samples").is_dir():
            return path
    raise ValueError(f"Cannot locate evaluation root above {campaign_dir}")


def _rubric_rows(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    visual = (verdict.get("visual_evidence") or {}).get("combined", {})
    resolutions = {
        item["id"]: item for item in visual.get("resolved", [])
        if item.get("accepted", True)
    }
    rows = []
    for item in verdict.get("rubrics", []):
        resolution = resolutions.get(item.get("id"))
        rows.append({
            "id": item.get("id"),
            "requirement": item.get("requirement", ""),
            "deterministic_status": item.get("status", "unverified"),
            "final_status": resolution.get("verdict") if resolution else item.get("status", "unverified"),
            "evidence_source": "visual" if resolution else "deterministic",
            "confidence": resolution.get("confidence") if resolution else None,
            "evidence": resolution.get("evidence", []) if resolution else item.get("evidence", []),
            "explanation": resolution.get("explanation", "") if resolution else "",
        })
    return rows


def generate_explorer_bundle(
    campaign_dir: Path,
    output_dir: Path,
    *,
    render_native: bool = False,
) -> dict[str, Any]:
    campaign_dir = Path(campaign_dir).resolve()
    output_dir = Path(output_dir).resolve()
    eval_root = _evaluation_root(campaign_dir)
    workspace = eval_root.parents[1]
    manifest = json.loads((campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8"))
    results = json.loads((campaign_dir / "results.json").read_text(encoding="utf-8"))
    validate_campaign_manifest(manifest)
    summary = summarize_campaign(manifest, results)
    replay = manifest.get("execution", {}).get("type") == "verifier-replay"
    baseline_index = {}
    if replay:
        baseline_id = manifest["execution"]["baseline_campaign_id"]
        baseline_results = json.loads(
            (eval_root / "batch" / baseline_id / "results.json").read_text(encoding="utf-8")
        )
        baseline_index = {
            (item["sample_id"], item["model"]): item for item in baseline_results
        }
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    runs = []
    for result in results:
        job_dir = Path(result["job_dir"]).resolve()
        sample_id = result["sample_id"]
        sample_dir = eval_root / "samples" / sample_id
        task = json.loads((sample_dir / "task_desc.json").read_text(encoding="utf-8"))
        verdict = json.loads((job_dir / "verdict.json").read_text(encoding="utf-8"))
        selected = result.get("selected_attempt_id") or ("verifier" if replay else None)
        candidate_image = None
        render_error = None
        native_output = assets / f"{sample_id[:8]}-{_slug(result['model'])}.png"
        if render_native:
            try:
                scene_path = job_dir / "scene.json"
                scene = json.loads(scene_path.read_text(encoding="utf-8")) if scene_path.is_file() else {}
                view = "isometric" if scene_has_3d(scene) else "top"
                candidate_source = (
                    eval_root / result["candidate_source"] if replay else job_dir / "candidate.dwg"
                )
                render_dwg_core(candidate_source, native_output, view=view)
            except Exception as exc:
                render_error = repr(exc)
        elif replay and (job_dir / "candidate-top.png").is_file():
            candidate_image = _workspace_url(job_dir / "candidate-top.png", workspace)
        if native_output.is_file():
            candidate_image = _workspace_url(native_output, workspace)
        else:
            fallback = job_dir / "attempts" / str(selected) / "candidate-render.png"
            if fallback.is_file():
                candidate_image = _workspace_url(fallback, workspace)
        reference_root = (
            Path(baseline_index[(sample_id, result["model"])]["job_dir"]) / "input_files"
            if replay else job_dir / "input_files"
        )
        references = [
            _workspace_url(path, workspace)
            for path in sorted(reference_root.glob("*"))
            if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
        ]
        attempts = []
        for attempt in result.get("attempts", []):
            attempts.append({
                "attempt_id": attempt.get("attempt_id"),
                "attempt_number": attempt.get("attempt_number"),
                "kind": attempt.get("kind"),
                "eqc": attempt.get("eqc", 0),
                "score": attempt.get("score", 0),
                "coverage": attempt.get("coverage", 0),
                "status": attempt.get("status"),
                "selected": attempt.get("attempt_id") == selected,
                "elapsed_seconds": attempt.get("elapsed_seconds", 0),
                "errors": attempt.get("errors", []),
            })
        if replay:
            attempts = [{
                "attempt_id": "verifier",
                "attempt_number": 1,
                "kind": "verifier-replay",
                "eqc": result.get("new_eqc", 0),
                "score": result.get("old_eqc", 0),
                "coverage": result.get("coverage", 0),
                "status": result.get("status"),
                "selected": True,
                "elapsed_seconds": result.get("elapsed_seconds", 0),
                "errors": result.get("errors", []),
            }]
        integrity = result.get("integrity", {})
        if replay:
            integrity = {
                "ok": (
                    not result.get("errors")
                    and result.get("new_eqc") is not None
                    and bool(result.get("candidate_sha256"))
                ),
            }
        runs.append({
            "run_id": result.get("run_id") or f"{manifest['campaign_id']}:{sample_id}:{result['model']}",
            "sample_id": sample_id,
            "sample_key": sample_id[:8],
            "domain": task.get("domain", "CAD"),
            "task": task.get("task", task.get("description", sample_id)),
            "model": result["model"],
            "status": result.get("status"),
            "eqc": result.get("new_eqc", result.get("eqc", 0)),
            "legacy_score": result.get("old_eqc", result.get("score", 0)),
            "deterministic_coverage": result.get("coverage", 0),
            "selected_attempt_id": selected,
            "elapsed_seconds": result.get("elapsed_seconds", 0),
            "integrity": integrity,
            "attempts": attempts,
            "rubrics": _rubric_rows(verdict),
            "candidate_image": candidate_image,
            "reference_images": references,
            "render_error": render_error,
        })
    payload = {
        "schema_version": "1.0",
        "campaign": summary,
        "models": [item["name"] for item in manifest["models"]],
        "runs": runs,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "explorer-data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return payload
