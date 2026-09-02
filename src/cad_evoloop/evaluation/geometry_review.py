"""Export geometry campaigns as evidence bundles for human adjudication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from cad_evoloop.ledger.ledger import redact, sha256_file


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PUBLIC_EVENT_TYPES = {"agent_message", "mcp_tool_call", "command_execution"}
RENDER_PROTOCOL = {
    "id": "evocad-orthographic-evidence-v1",
    "resolution": [960, 720],
    "camera_direction": [1.0, -1.25, 0.85],
    "candidate_color": [223, 132, 61],
    "ground_truth_color": [67, 151, 184],
    "alignment_scale_allowed": False,
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _file_evidence(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def _copy_asset(source: Path, assets: Path, name: str) -> str | None:
    if not source.is_file():
        return None
    destination = assets / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return "assets/" + destination.relative_to(assets).as_posix()


def _snapshot_review_system(
    output_dir: Path, agent_loop_protocol: str | None,
) -> dict[str, Any]:
    implementation_root = Path(__file__).resolve().parents[3]
    app_sources = [
        (implementation_root / "apps/geometry-review/index.html", Path("index.html")),
        (implementation_root / "apps/geometry-review/app.js", Path("app.js")),
        (
            implementation_root / "apps/geometry-review/geometry-viewer.js",
            Path("geometry-viewer.js"),
        ),
        (implementation_root / "apps/geometry-review/styles.css", Path("styles.css")),
        (
            implementation_root / "apps/geometry-review/vendor/three/three.module.min.js",
            Path("vendor/three/three.module.min.js"),
        ),
        (
            implementation_root / "apps/geometry-review/vendor/three/three.core.min.js",
            Path("vendor/three/three.core.min.js"),
        ),
        (
            implementation_root / "apps/geometry-review/vendor/three/addons/controls/OrbitControls.js",
            Path("vendor/three/addons/controls/OrbitControls.js"),
        ),
        (
            implementation_root / "apps/geometry-review/vendor/three/addons/loaders/STLLoader.js",
            Path("vendor/three/addons/loaders/STLLoader.js"),
        ),
        (
            implementation_root / "apps/geometry-review/vendor/three/LICENSE.txt",
            Path("vendor/three/LICENSE.txt"),
        ),
        (
            implementation_root / "apps/geometry-review/vendor/README.md",
            Path("vendor/README.md"),
        ),
    ]
    loop_protocol_file = {
        "evocad-agent-loop-v2": "agent-loop-v2.json",
        "evocad-agent-loop-v3": "agent-loop-v3.json",
    }.get(agent_loop_protocol, "agent-loop-v3.json")
    source_files = [
        Path(__file__).resolve(),
        Path(__file__).with_name("human_review.py").resolve(),
        (Path(__file__).parent / "schemas/human-geometry-review.schema.json").resolve(),
        (Path(__file__).parent / "schemas/geometry-agent-decision.schema.json").resolve(),
        (implementation_root / f"evals/geometry-benchmarks/{loop_protocol_file}").resolve(),
        (implementation_root / "evals/geometry-benchmarks/prompts/adjudicate.md").resolve(),
    ]

    def snapshot(source: Path, destination: Path) -> dict[str, Any]:
        if not source.is_file():
            raise FileNotFoundError(f"Review system source is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {
            "source": source.name,
            "path": destination.relative_to(output_dir).as_posix(),
            **(_file_evidence(destination) or {}),
        }

    app_records = [
        snapshot(source, output_dir / "app" / relative)
        for source, relative in app_sources
    ]
    source_records = [
        snapshot(source, output_dir / "review-system" / source.name) for source in source_files
    ]
    return {
        "ui_version": "1.0",
        "render_protocol": RENDER_PROTOCOL,
        "served_app": app_records,
        "source_snapshot": source_records,
    }


def _find_source_manifest(workspace: Path, expected_sha256: str) -> Path | None:
    candidates = [
        *workspace.glob(".local/datasets/**/manifest.json"),
        *workspace.glob("evals/geometry-benchmarks/**/manifest.json"),
    ]
    for candidate in candidates:
        if candidate.is_file() and sha256_file(candidate) == expected_sha256:
            return candidate.resolve()
    return None


def _public_events(path: Path, phase: str) -> list[dict[str, Any]]:
    events = []
    for value in _read_jsonl(path):
        if value.get("type") != "item.completed":
            continue
        item = value.get("item") or {}
        if item.get("type") not in PUBLIC_EVENT_TYPES:
            continue
        event = {
            "type": item.get("type"),
            "status": item.get("status", "completed"),
            "phase": phase,
        }
        if item.get("type") == "agent_message":
            event["text"] = item.get("text", "")
        elif item.get("type") == "mcp_tool_call":
            event.update({
                "tool": item.get("tool"),
                "server": item.get("server"),
                "arguments": redact(item.get("arguments") or {}),
                "error": item.get("error"),
            })
        else:
            event.update({
                "command": item.get("command", ""),
                "exit_code": item.get("exit_code"),
            })
        events.append(event)
    return events


def _mcp_events(path: Path) -> list[dict[str, Any]]:
    rows = []
    for value in _read_jsonl(path):
        rows.append({
            "event_id": value.get("event_id"),
            "timestamp": value.get("timestamp"),
            "tool": value.get("tool"),
            "status": value.get("status"),
            "duration_ms": value.get("duration_ms"),
            "arguments": redact(value.get("arguments") or {}),
            "error": value.get("error") or (
                (value.get("response") or {}).get("error")
                if isinstance(value.get("response"), dict) else None
            ),
        })
    return rows


def _projection(vertices, width: int, height: int, bounds=None):
    import numpy as np

    direction = np.asarray([1.0, -1.25, 0.85])
    direction /= np.linalg.norm(direction)
    up = np.asarray([0.0, 0.0, 1.0])
    horizontal = np.cross(up, direction)
    horizontal /= np.linalg.norm(horizontal)
    vertical = np.cross(direction, horizontal)
    projected = np.column_stack((vertices @ horizontal, vertices @ vertical, vertices @ direction))
    fit = projected[:, :2] if bounds is None else bounds
    low = fit.min(axis=0)
    high = fit.max(axis=0)
    span = np.maximum(high - low, 1e-9)
    scale = min((width - 96) / span[0], (height - 96) / span[1])
    center = (low + high) / 2.0
    xy = (projected[:, :2] - center) * scale
    xy[:, 0] += width / 2.0
    xy[:, 1] = height / 2.0 - xy[:, 1]
    return xy, projected[:, 2], projected[:, :2]


def _draw_meshes(meshes: Iterable[tuple[Any, tuple[int, int, int, int]]], output: Path) -> None:
    """Render a deterministic orthographic evidence image without an OpenGL dependency."""
    from PIL import Image, ImageDraw
    import numpy as np

    meshes = list(meshes)
    width, height = 960, 720
    all_vertices = np.vstack([np.asarray(mesh.vertices) for mesh, _ in meshes])
    _, _, common_bounds = _projection(all_vertices, width, height)
    image = Image.new("RGBA", (width, height), (28, 35, 42, 255))
    light = np.asarray([0.35, -0.45, 0.82])
    light /= np.linalg.norm(light)
    for mesh, color in meshes:
        vertices = np.asarray(mesh.vertices)
        xy, depth, _ = _projection(vertices, width, height, common_bounds)
        triangles = []
        for face in np.asarray(mesh.faces):
            face = face.astype(int)
            triangle = vertices[face]
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            length = float(np.linalg.norm(normal))
            intensity = 0.62 if length <= 1e-12 else 0.58 + 0.42 * abs(float(normal @ light) / length)
            shaded = tuple(max(0, min(255, round(channel * intensity))) for channel in color[:3]) + (color[3],)
            triangles.append((float(depth[face].mean()), xy[face], shaded))
        triangles.sort(key=lambda item: item[0])
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        drawing = ImageDraw.Draw(layer, "RGBA")
        outline = (238, 242, 244, min(115, color[3])) if len(triangles) <= 500 else None
        for _, points, shaded in triangles:
            polygon = [tuple(float(value) for value in point) for point in points]
            drawing.polygon(polygon, fill=shaded, outline=outline)
        image = Image.alpha_composite(image, layer)
    image.convert("RGB").save(output, quality=92)


def _align_candidate(candidate, ground_truth, verdict: dict[str, Any]):
    import numpy as np

    aligned = candidate.copy()
    rotation = np.asarray((verdict.get("alignment") or {}).get("rotation"), dtype=float)
    if rotation.shape != (3, 3):
        rotation = np.eye(3)
    aligned.vertices = (
        (aligned.vertices - aligned.bounds.mean(axis=0)) @ rotation.T
        + ground_truth.bounds.mean(axis=0)
    )
    return aligned


def _render_geometry_evidence(
    candidate,
    ground_truth,
    candidate_output: Path,
    overlay_output: Path,
) -> None:
    _draw_meshes([(candidate, (223, 132, 61, 220))], candidate_output)
    _draw_meshes([
        (ground_truth, (67, 151, 184, 105)),
        (candidate, (223, 132, 61, 145)),
    ], overlay_output)


def _export_stl(mesh, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(output), file_type="stl")


def generate_geometry_review_bundle(
    campaign_dir: str | Path,
    output_dir: str | Path,
    *,
    source_manifest: str | Path | None = None,
    annotations_path: str | Path | None = None,
    render_geometry: bool = False,
) -> dict[str, Any]:
    """Create a self-contained review bundle from cached campaign artifacts."""
    campaign_dir = Path(campaign_dir).resolve()
    output_dir = Path(output_dir).resolve()
    workspace = campaign_dir
    while workspace.parent != workspace and not (workspace / "pyproject.toml").is_file():
        workspace = workspace.parent
    if not (workspace / "pyproject.toml").is_file():
        raise ValueError(f"Cannot locate workspace above {campaign_dir}")
    manifest_path = campaign_dir / "campaign-manifest.json"
    manifest = _read_json(manifest_path)
    results = _read_json(campaign_dir / "results.json")
    if not isinstance(manifest, dict) or not isinstance(results, list):
        raise ValueError(f"Incomplete geometry campaign: {campaign_dir}")
    expected_source = manifest.get("source_manifest_sha256", "")
    resolved_source = Path(source_manifest).resolve() if source_manifest else _find_source_manifest(
        workspace, expected_source,
    )
    if resolved_source and sha256_file(resolved_source) != expected_source:
        raise ValueError("Source manifest hash does not match the campaign binding")
    source_value = _read_json(resolved_source, {}) if resolved_source else {}
    samples = {item["sample_id"]: item for item in source_value.get("samples", [])}
    annotations = _read_json(Path(annotations_path).resolve(), {}) if annotations_path else {}
    annotation_rows = annotations.get("samples", {}) if isinstance(annotations, dict) else {}
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    review_system = _snapshot_review_system(output_dir, manifest.get("agent_loop_protocol"))
    runs = []
    for result in results:
        job_dir = Path(result["job_dir"]).resolve()
        sample_id = result["sample_id"]
        model = result["model"]
        target_id = hashlib.sha256(
            f"{manifest['campaign_id']}\0{sample_id}\0{model}".encode("utf-8")
        ).hexdigest()[:20]
        asset_root = Path(_slug(sample_id)) / _slug(model)
        task = _read_json(job_dir / "task.json", {})
        input_images = []
        input_evidence = []
        for index, path in enumerate(sorted((job_dir / "input_files").glob("*")), start=1):
            if path.suffix.casefold() in IMAGE_SUFFIXES:
                copied = _copy_asset(path, assets, str(asset_root / f"input-{index:02d}{path.suffix.casefold()}"))
                if copied:
                    input_images.append(copied)
                    copied_path = output_dir / copied
                    input_evidence.append({"path": copied, **(_file_evidence(copied_path) or {})})
        sample = samples.get(sample_id, {})
        ground_truth = None
        if resolved_source and sample.get("ground_truth_step"):
            ground_truth = (resolved_source.parent / sample["ground_truth_step"]).resolve()
        truth_render = assets / asset_root / "ground-truth.png"
        truth_geometry = assets / asset_root / "ground-truth.stl"
        truth_render.unlink(missing_ok=True)
        truth_geometry.unlink(missing_ok=True)
        ground_truth_mesh = None
        ground_truth_error = None
        if render_geometry and ground_truth and ground_truth.is_file():
            try:
                from .geometry_score import _load_mesh

                ground_truth_mesh = _load_mesh(ground_truth)
                _export_stl(ground_truth_mesh, truth_geometry)
                _draw_meshes([(ground_truth_mesh, (67, 151, 184, 235))], truth_render)
            except Exception as exc:
                ground_truth_error = repr(exc)
        attempts = []
        for attempt_result in result.get("attempts", []):
            attempt_id = str(attempt_result["attempt_id"])
            attempt_dir = job_dir / "attempts" / attempt_id
            verdict_path = attempt_dir / "geometry-verdict.json"
            reflection_path = attempt_dir / "reflection.json"
            feedback_path = attempt_dir / "feedback-packet.json"
            events_path = attempt_dir / "codex-events.jsonl"
            reflection_events_path = attempt_dir / "reflection-events.jsonl"
            reflection_stderr_path = attempt_dir / "reflection-stderr.log"
            audit_path = attempt_dir / "mcp-audit.jsonl"
            candidate_path = attempt_dir / "candidate.stl"
            parse_errors = []
            try:
                verdict = _read_json(verdict_path, {})
            except (json.JSONDecodeError, UnicodeError) as exc:
                verdict = {}
                parse_errors.append({"artifact": "geometry-verdict.json", "error": str(exc)})
            try:
                reflection = _read_json(reflection_path)
            except (json.JSONDecodeError, UnicodeError) as exc:
                reflection = None
                parse_errors.append({"artifact": "reflection.json", "error": str(exc)})
            try:
                feedback_packet = _read_json(feedback_path)
            except (json.JSONDecodeError, UnicodeError) as exc:
                feedback_packet = None
                parse_errors.append({"artifact": "feedback-packet.json", "error": str(exc)})
            candidate_render = assets / asset_root / f"{attempt_id}-candidate.png"
            overlay_render = assets / asset_root / f"{attempt_id}-overlay.png"
            candidate_geometry = assets / asset_root / f"{attempt_id}-candidate.stl"
            localization_asset = assets / asset_root / f"{attempt_id}-localization.json"
            candidate_render.unlink(missing_ok=True)
            overlay_render.unlink(missing_ok=True)
            candidate_geometry.unlink(missing_ok=True)
            localization_asset.unlink(missing_ok=True)
            render_error = ground_truth_error
            localization_error = None
            localization_summary = None
            localization_cache = None
            candidate_mesh = None
            if render_geometry and candidate_path.is_file() and ground_truth_mesh is not None:
                try:
                    from .geometry_score import _load_mesh

                    candidate_mesh = _align_candidate(
                        _load_mesh(candidate_path), ground_truth_mesh, verdict,
                    )
                    _export_stl(candidate_mesh, candidate_geometry)
                    _render_geometry_evidence(
                        candidate_mesh, ground_truth_mesh, candidate_render, overlay_render,
                    )
                except Exception as exc:
                    render_error = repr(exc)
            if candidate_mesh is not None and ground_truth_mesh is not None:
                try:
                    from .geometry_localization import localize_surface_mismatch
                    from .geometry_score import _dependencies

                    _, np, cKDTree, trimesh = _dependencies()
                    reference_localization = (
                        (verdict.get("mismatch") or {}).get("localization") or {}
                    )
                    configured_samples = int(reference_localization.get(
                        "surface_samples_per_direction", 4000,
                    ))
                    visualization_samples = max(1000, min(configured_samples, 4000))
                    cache_binding = {
                        "protocol": "evocad-surface-localization-v1",
                        "implementation_sha256": sha256_file(
                            Path(__file__).with_name("geometry_localization.py")
                        ),
                        "candidate_sha256": sha256_file(candidate_path),
                        "ground_truth_sha256": sha256_file(ground_truth),
                        "alignment": verdict.get("alignment"),
                        "surface_samples_per_direction": visualization_samples,
                        "max_visualization_points": 1600,
                    }
                    cache_key = _canonical_sha256(cache_binding)
                    cache_path = (
                        workspace / ".local/cache/geometry-localization"
                        / f"{cache_key}.json"
                    )
                    cache_hit = cache_path.is_file()
                    visual_localization = _read_json(cache_path) if cache_hit else None
                    if not isinstance(visual_localization, dict):
                        visual_localization = localize_surface_mismatch(
                            candidate_mesh,
                            ground_truth_mesh,
                            sample_count=visualization_samples,
                            cKDTree=cKDTree,
                            np=np,
                            trimesh=trimesh,
                            include_visualization=True,
                            max_visualization_points=1600,
                        )
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(
                            json.dumps(visual_localization, separators=(",", ":")) + "\n",
                            encoding="utf-8",
                        )
                    localization_cache = {"key": cache_key, "hit": cache_hit}
                    if reference_localization:
                        localization = {
                            **reference_localization,
                            "visualization": visual_localization.get("visualization", {}),
                            "visualization_surface_samples_per_direction": visualization_samples,
                            "region_summary_source": "geometry-verdict.json",
                        }
                        reference_by_direction = {
                            direction: [
                                region for region in reference_localization.get("regions", [])
                                if region.get("direction") == direction
                            ]
                            for direction in (
                                "candidate_to_ground_truth", "ground_truth_to_candidate",
                            )
                        }
                        for direction, points in localization["visualization"].items():
                            reference_regions = reference_by_direction.get(direction, [])
                            if not reference_regions:
                                continue
                            centers = np.asarray([
                                region["centroid"] for region in reference_regions
                            ], dtype=float)
                            for point in points:
                                distances = np.linalg.norm(
                                    centers - np.asarray(point["point"], dtype=float), axis=1,
                                )
                                point["region_id"] = reference_regions[
                                    int(np.argmin(distances))
                                ]["region_id"]
                    else:
                        localization = visual_localization
                    localization_asset.write_text(
                        json.dumps(localization, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    localization_summary = {
                        key: value
                        for key, value in localization.items()
                        if key != "visualization"
                    }
                except Exception as exc:
                    localization_error = repr(exc)
            evidence = {
                "candidate": _file_evidence(candidate_path),
                "verdict": _file_evidence(verdict_path),
                "reflection": _file_evidence(reflection_path),
                "feedback_packet": _file_evidence(feedback_path),
                "codex_events": _file_evidence(events_path),
                "reflection_events": _file_evidence(reflection_events_path),
                "reflection_stderr": _file_evidence(reflection_stderr_path),
                "mcp_audit": _file_evidence(audit_path),
                "render_images": {
                    "candidate": _file_evidence(candidate_render),
                    "overlay": _file_evidence(overlay_render),
                    "ground_truth": _file_evidence(truth_render),
                },
                "geometry_assets": {
                    "candidate": _file_evidence(candidate_geometry),
                    "ground_truth": _file_evidence(truth_geometry),
                    "localization": _file_evidence(localization_asset),
                },
            }
            attempts.append({
                **{key: attempt_result.get(key) for key in (
                    "attempt_id", "attempt_number", "elapsed_seconds", "return_code",
                    "timed_out", "action_timed_out", "decision_timed_out",
                    "decision_return_code", "decision_transport_retries",
                    "decision_recovered", "decision_attempts", "score", "passed",
                    "thread_id", "usage",
                    "action_usage", "reflection_usage", "errors", "agent_decision",
                    "decision_reason", "can_improve", "stagnation_advisory",
                    "safety_stop_reason",
                )},
                "selected": attempt_id == result.get("selected_attempt_id"),
                "verdict": verdict,
                "reflection": reflection,
                "feedback_packet": feedback_packet,
                "public_events": [
                    *_public_events(events_path, "action"),
                    *_public_events(reflection_events_path, "feedback"),
                ],
                "mcp_events": _mcp_events(audit_path),
                "evidence": evidence,
                "evidence_sha256": _canonical_sha256(evidence),
                "images": {
                    "candidate": "assets/" + candidate_render.relative_to(assets).as_posix()
                    if candidate_render.is_file() else None,
                    "overlay": "assets/" + overlay_render.relative_to(assets).as_posix()
                    if overlay_render.is_file() else None,
                    "ground_truth": "assets/" + truth_render.relative_to(assets).as_posix()
                    if truth_render.is_file() else None,
                },
                "geometry": {
                    "candidate": "assets/" + candidate_geometry.relative_to(assets).as_posix()
                    if candidate_geometry.is_file() else None,
                    "ground_truth": "assets/" + truth_geometry.relative_to(assets).as_posix()
                    if truth_geometry.is_file() else None,
                    "localization": "assets/" + localization_asset.relative_to(assets).as_posix()
                    if localization_asset.is_file() else None,
                },
                "render_error": render_error,
                "localization_error": localization_error,
                "localization": localization_summary,
                "localization_cache": localization_cache,
                "parse_errors": parse_errors,
            })
        selected_attempt = next(
            (item for item in attempts if item["selected"]), attempts[-1] if attempts else None,
        )
        runs.append({
            "target_id": target_id,
            "run_id": result.get("run_id"),
            "sample_id": sample_id,
            "sample_key": sample_id.replace(":", " / "),
            "dataset": task.get("dataset", sample.get("dataset", "unknown")),
            "category": task.get("category", sample.get("category")),
            "task": task.get("task", sample.get("task", sample_id)),
            "model": model,
            "reasoning_effort": result.get("reasoning_effort"),
            "status": result.get("status"),
            "score": result.get("score"),
            "passed": result.get("passed"),
            "selected_attempt_id": result.get("selected_attempt_id"),
            "stop_reason": result.get("stop_reason"),
            "agent_requested_continue": result.get("agent_requested_continue"),
            "selected_evidence_sha256": selected_attempt.get("evidence_sha256") if selected_attempt else None,
            "candidate_sha256": result.get("candidate_sha256"),
            "ground_truth_sha256": result.get("ground_truth_sha256"),
            "integrity": result.get("integrity"),
            "input_images": input_images,
            "input_evidence": input_evidence,
            "data_quality_annotation": annotation_rows.get(sample_id),
            "attempts": attempts,
        })
    campaign_binding = {
        "campaign_id": manifest["campaign_id"],
        "campaign_manifest_sha256": sha256_file(manifest_path),
        "declared_manifest_sha256": manifest.get("manifest_sha256"),
        "source_manifest_sha256": expected_source,
        "protocol": manifest.get("protocol"),
        "agent_loop_protocol": manifest.get("agent_loop_protocol"),
        "benchmark_split": manifest.get("benchmark_split"),
        "execution": manifest.get("execution"),
    }
    payload = {
        "schema_version": "1.0",
        "review_ui_version": "1.0",
        "review_system": review_system,
        "campaign": campaign_binding,
        "models": [item.get("name") for item in manifest.get("models", [])],
        "source_manifest_available": bool(resolved_source),
        "render_geometry": render_geometry,
        "runs": runs,
    }
    payload["bundle_sha256"] = _canonical_sha256(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "review-data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return payload
