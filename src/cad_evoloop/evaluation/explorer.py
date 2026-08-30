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


def _rubric_rows(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    visual = verdict.get("visual_evidence", {}).get("combined", {})
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
    workspace = campaign_dir.parents[3]
    manifest = json.loads((campaign_dir / "campaign-manifest.json").read_text(encoding="utf-8"))
    results = json.loads((campaign_dir / "results.json").read_text(encoding="utf-8"))
    validate_campaign_manifest(manifest)
    summary = summarize_campaign(manifest, results)
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    runs = []
    for result in results:
        job_dir = Path(result["job_dir"]).resolve()
        sample_id = result["sample_id"]
        sample_dir = campaign_dir.parents[1] / "samples" / sample_id
        task = json.loads((sample_dir / "task_desc.json").read_text(encoding="utf-8"))
        verdict = json.loads((job_dir / "verdict.json").read_text(encoding="utf-8"))
        selected = result.get("selected_attempt_id")
        candidate_image = None
        render_error = None
        native_output = assets / f"{sample_id[:8]}-{_slug(result['model'])}.png"
        if render_native:
            try:
                scene_path = job_dir / "scene.json"
                scene = json.loads(scene_path.read_text(encoding="utf-8")) if scene_path.is_file() else {}
                view = "isometric" if scene_has_3d(scene) else "top"
                render_dwg_core(job_dir / "candidate.dwg", native_output, view=view)
            except Exception as exc:
                render_error = repr(exc)
        if native_output.is_file():
            candidate_image = _workspace_url(native_output, workspace)
        else:
            fallback = job_dir / "attempts" / str(selected) / "candidate-render.png"
            if fallback.is_file():
                candidate_image = _workspace_url(fallback, workspace)
        references = [
            _workspace_url(path, workspace)
            for path in sorted((job_dir / "input_files").glob("*"))
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
        runs.append({
            "run_id": result.get("run_id"),
            "sample_id": sample_id,
            "sample_key": sample_id[:8],
            "domain": task.get("domain", "CAD"),
            "task": task.get("task", task.get("description", sample_id)),
            "model": result["model"],
            "status": result.get("status"),
            "eqc": result.get("eqc", 0),
            "legacy_score": result.get("score", 0),
            "deterministic_coverage": result.get("coverage", 0),
            "selected_attempt_id": selected,
            "elapsed_seconds": result.get("elapsed_seconds", 0),
            "integrity": result.get("integrity", {}),
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
