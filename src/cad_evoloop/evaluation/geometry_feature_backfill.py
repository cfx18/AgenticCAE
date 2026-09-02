"""Derive native feature localization for frozen geometry campaign checkpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cad_evoloop.backends.autocad.topology import build_topology_plugin, export_topology_core
from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root

from .geometry_campaign import _operation_manifest_from_audit, geometry_verdict
from .geometry_features import enrich_score_with_topology, face_query_rows, load_topology
from .geometry_score import score_geometry_files


BACKFILL_PROTOCOL_ID = "evocad-native-feature-backfill-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_hash(value: dict[str, Any], digest_key: str | None = None) -> str:
    body = {key: item for key, item in value.items() if key != digest_key}
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inside(path: str | Path, root: Path, name: str) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} must be inside workspace: {root}") from exc
    return resolved


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_immutable_manifest(path: Path, value: dict[str, Any]) -> None:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise ValueError(f"Backfill manifest is immutable and differs: {path}")
        return
    _write_json(path, value)


def _artifact(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "completed":
        return {
            "sample_id": record["sample_id"], "model": record["model"],
            "selected_attempt_id": record.get("selected_attempt_id"),
            "status": record.get("status"), "error": record.get("error"),
        }
    verdict = json.loads(Path(record["artifacts"]["verdict"]["path"]).read_text(encoding="utf-8"))
    localization = ((verdict.get("mismatch") or {}).get("localization") or {})
    regions = localization.get("regions", [])
    exact_mapped = sum(bool((item.get("exact_face_query") or {}).get("mapped")) for item in regions)
    face_mapped = sum(bool(item.get("candidate_topology_faces")) for item in regions)
    high_confidence = sum(item.get("topology_mapping_confidence") == "high" for item in regions)
    return {
        "sample_id": record["sample_id"], "model": record["model"],
        "selected_attempt_id": record["selected_attempt_id"], "status": "completed",
        "score": verdict.get("score"), "passed": verdict.get("passed"),
        "region_count": len(regions), "face_mapped_region_count": face_mapped,
        "exact_mapped_region_count": exact_mapped,
        "high_confidence_region_count": high_confidence,
        "native_face_count": (localization.get("native_topology") or {}).get("face_count", 0),
        "native_feature_candidate_count": (
            localization.get("native_topology") or {}
        ).get("feature_candidate_count", 0),
        "record": record["record_path"],
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    eligible = [row for row in completed if row.get("region_count", 0) > 0]
    regions = sum(row.get("region_count", 0) for row in completed)
    exact = sum(row.get("exact_mapped_region_count", 0) for row in completed)
    face_mapped = sum(row.get("face_mapped_region_count", 0) for row in completed)
    return {
        "sample_count": len(rows),
        "completed_sample_count": len(completed),
        "failed_sample_count": len(rows) - len(completed),
        "samples_with_mismatch_regions": len(eligible),
        "sample_topology_success_rate": round(100 * len(completed) / max(len(rows), 1), 2),
        "region_count": regions,
        "face_mapped_region_count": face_mapped,
        "face_mapping_coverage_percent": round(100 * face_mapped / max(regions, 1), 2),
        "exact_mapped_region_count": exact,
        "exact_face_mapping_coverage_percent": round(100 * exact / max(regions, 1), 2),
        "high_confidence_region_count": sum(
            row.get("high_confidence_region_count", 0) for row in completed
        ),
    }


def backfill_geometry_features(
    campaign_dir: str | Path,
    source_manifest: str | Path,
    output_dir: str | Path,
    *,
    sample_count: int = 20000,
    voxel_resolution: int = 64,
    timeout: int = 180,
    max_jobs: int | None = None,
) -> dict[str, Any]:
    """Backfill selected checkpoints without modifying the source campaign."""
    workspace = project_root().resolve()
    campaign_dir = _inside(campaign_dir, workspace, "campaign_dir")
    source_manifest = _inside(source_manifest, workspace, "source_manifest")
    output_dir = _inside(output_dir, workspace, "output_dir")
    campaign_manifest_path = campaign_dir / "campaign-manifest.json"
    results_path = campaign_dir / "results.json"
    if not campaign_manifest_path.is_file() or not results_path.is_file():
        raise ValueError(f"Incomplete geometry campaign: {campaign_dir}")
    campaign_manifest = json.loads(campaign_manifest_path.read_text(encoding="utf-8"))
    if sha256_file(source_manifest) != campaign_manifest.get("source_manifest_sha256"):
        raise ValueError("Source manifest hash does not match the campaign binding")
    source_value = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_samples = {item["sample_id"]: item for item in source_value.get("samples", [])}
    results = json.loads(results_path.read_text(encoding="utf-8"))
    selected_results = results[:max_jobs] if max_jobs is not None else results

    executable = Path(os.environ.get(
        "AUTOCAD_CORE_CONSOLE", r"E:\AutoCAD\AutoCAD 2024\accoreconsole.exe",
    )).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"AutoCAD Core Console not found: {executable}")
    plugin_override = os.environ.get("AUTOCAD_TOPOLOGY_PLUGIN")
    plugin = (
        Path(plugin_override).resolve() if plugin_override
        else build_topology_plugin(
            workspace,
            managed_dir=Path(os.environ.get("AUTOCAD_MANAGED_DIR", str(executable.parent))),
        )
    )
    existing_manifest_path = output_dir / "backfill-manifest.json"
    existing_manifest = (
        json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        if existing_manifest_path.is_file() else None
    )
    manifest = {
        "schema_version": "1.0",
        "protocol": BACKFILL_PROTOCOL_ID,
        "created_at": existing_manifest.get("created_at") if existing_manifest else _utc_now(),
        "source_campaign": {
            "campaign_id": campaign_manifest.get("campaign_id"),
            "campaign_manifest_sha256": sha256_file(campaign_manifest_path),
            "results_sha256": sha256_file(results_path),
        },
        "source_manifest_sha256": sha256_file(source_manifest),
        "selection": "selected_checkpoint",
        "sample_ids": [item["sample_id"] for item in selected_results],
        "parameters": {
            "surface_samples": sample_count,
            "voxel_resolution": voxel_resolution,
            "topology_timeout_seconds": timeout,
        },
        "implementations": {
            "backfill": sha256_file(Path(__file__)),
            "feature_localization": sha256_file(Path(__file__).with_name("geometry_features.py")),
            "geometry_score": sha256_file(Path(__file__).with_name("geometry_score.py")),
            "topology_plugin_source": sha256_file(
                workspace / "mcp/autocad-topology/EvoCadTopology.cs"
            ),
        },
    }
    manifest["manifest_sha256"] = _canonical_hash(manifest, "manifest_sha256")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_immutable_manifest(existing_manifest_path, manifest)

    records = []
    for result in selected_results:
        sample_id = result["sample_id"]
        model = result["model"]
        attempt_id = result.get("selected_attempt_id")
        job_dir = _inside(result["job_dir"], campaign_dir, "result.job_dir")
        record_dir = output_dir / _slug(sample_id) / _slug(model) / str(attempt_id or "none")
        record_path = record_dir / "record.json"
        if record_path.is_file():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            records.append(record)
            continue
        record_dir.mkdir(parents=True, exist_ok=True)
        candidate_dwg = job_dir / "candidate.dwg"
        candidate_stl = job_dir / "candidate.stl"
        prior_verdict = job_dir / "geometry-verdict.json"
        attempt_dir = job_dir / "attempts" / str(attempt_id)
        audit_path = attempt_dir / "mcp-audit.jsonl"
        sample = source_samples.get(sample_id)
        record: dict[str, Any] = {
            "schema_version": "1.0", "protocol": BACKFILL_PROTOCOL_ID,
            "sample_id": sample_id, "model": model, "selected_attempt_id": attempt_id,
            "status": "running", "record_path": str(record_path),
            "source_artifacts": {
                "candidate_dwg": _artifact(candidate_dwg),
                "candidate_stl": _artifact(candidate_stl),
                "prior_verdict": _artifact(prior_verdict),
                "mcp_audit": _artifact(audit_path),
            },
        }
        try:
            if not attempt_id or sample is None:
                raise ValueError("Selected attempt or source sample is unavailable")
            ground_truth = _inside(
                source_manifest.parent / sample["ground_truth_step"], workspace, "ground_truth",
            )
            if not candidate_dwg.is_file() or not candidate_stl.is_file() or not ground_truth.is_file():
                raise FileNotFoundError("Selected candidate DWG/STL or ground truth is unavailable")
            score = score_geometry_files(
                candidate_stl, ground_truth,
                sample_count=sample_count, voxel_resolution=voxel_resolution,
            )
            topology_path = record_dir / "candidate-topology.json"
            query_input = record_dir / "face-query.tsv"
            query_output = record_dir / "face-query.json"
            query_rows = face_query_rows(
                score["mismatch"]["localization"], score["alignment"],
            )
            if query_rows:
                query_input.write_text("".join(
                    f"{query_id}\t{x:.17g}\t{y:.17g}\t{z:.17g}\n"
                    for query_id, (x, y, z) in query_rows
                ), encoding="utf-8", newline="\n")
            export_topology_core(
                workspace, candidate_dwg, topology_path,
                executable=executable, plugin=plugin, timeout=timeout,
                query_input_path=query_input if query_rows else None,
                query_output_path=query_output if query_rows else None,
                query_source_center=score["alignment"]["candidate_center"],
            )
            query = (
                json.loads(query_output.read_text(encoding="utf-8"))
                if query_output.is_file() else None
            )
            score = enrich_score_with_topology(
                score, load_topology(topology_path),
                operations=_operation_manifest_from_audit(audit_path), query=query,
            )
            verdict_path = record_dir / "geometry-verdict.json"
            _write_json(verdict_path, geometry_verdict(score, sample_id))
            record.update({
                "status": "completed", "completed_at": _utc_now(),
                "ground_truth": _artifact(ground_truth),
                "artifacts": {
                    "verdict": _artifact(verdict_path), "topology": _artifact(topology_path),
                    "face_query": _artifact(query_output), "face_query_input": _artifact(query_input),
                },
            })
        except Exception as exc:
            record.update(status="failed", completed_at=_utc_now(), error=repr(exc))
        _write_json(record_path, record)
        records.append(record)

    rows = [_record_summary(record) for record in records]
    summary = {
        "schema_version": "1.0", "protocol": BACKFILL_PROTOCOL_ID,
        "manifest_sha256": manifest["manifest_sha256"],
        "source_campaign_id": campaign_manifest.get("campaign_id"),
        "generated_at": _utc_now(), "metrics": _aggregate(rows), "samples": rows,
    }
    summary["summary_sha256"] = _canonical_hash(summary, "summary_sha256")
    _write_json(output_dir / "summary.json", summary)
    return summary
