"""Deterministic, geometry-grounded comparison for STEP and mesh candidates."""

from __future__ import annotations

import itertools
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from .geometry_localization import localize_surface_mismatch


PROTOCOL_ID = "evocad-geometry-v2"
DEFAULT_THRESHOLDS = {
    "voxel_iou_min": 0.99,
    "normalized_chamfer_max": 0.006,
    "bbox_relative_error_max": 0.002,
    "volume_relative_error_max": 0.005,
    "candidate_watertight": True,
}
ACCEPTABLE_THRESHOLDS = {
    "voxel_iou_min": 0.95,
    "normalized_chamfer_max": 0.01,
    "bbox_relative_error_max": 0.01,
    "volume_relative_error_max": 0.02,
    "candidate_watertight": True,
}


def _dependencies():
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
        import numpy as np
        from scipy.spatial import cKDTree
        import trimesh
    except ImportError as exc:
        raise RuntimeError(
            "Geometry scoring requires the 'geometry' extra: "
            "install with `pip install -e .[geometry]`."
        ) from exc
    ocp = {
        "BRep_Tool": BRep_Tool,
        "BRepAdaptor_Surface": BRepAdaptor_Surface,
        "BRepMesh_IncrementalMesh": BRepMesh_IncrementalMesh,
        "IFSelect_RetDone": IFSelect_RetDone,
        "STEPControl_Reader": STEPControl_Reader,
        "TopAbs_FACE": TopAbs_FACE,
        "TopAbs_REVERSED": TopAbs_REVERSED,
        "TopExp_Explorer": TopExp_Explorer,
        "TopLoc_Location": TopLoc_Location,
        "TopoDS": TopoDS,
    }
    return ocp, np, cKDTree, trimesh


def _load_step_mesh(path: Path, *, tessellation: float, ocp, np, trimesh):
    reader = ocp["STEPControl_Reader"]()
    if reader.ReadFile(str(path)) != ocp["IFSelect_RetDone"]:
        raise ValueError(f"OpenCascade could not read STEP geometry: {path}")
    if reader.TransferRoots() <= 0:
        raise ValueError(f"STEP geometry contains no transferable roots: {path}")
    shape = reader.OneShape()
    mesher = ocp["BRepMesh_IncrementalMesh"](
        shape, tessellation, False, 0.1, True,
    )
    mesher.Perform()

    vertices = []
    triangles = []
    triangle_face_indices = []
    face_surfaces = []
    explorer = ocp["TopExp_Explorer"](shape, ocp["TopAbs_FACE"])
    while explorer.More():
        face = ocp["TopoDS"].Face_s(explorer.Current())
        adaptor = ocp["BRepAdaptor_Surface"](face)
        surface_code = int(adaptor.GetType())
        surface_names = {
            0: "plane", 1: "cylinder", 2: "cone", 3: "sphere", 4: "torus",
            5: "bezier", 6: "bspline", 7: "revolution", 8: "extrusion", 9: "offset",
            10: "other",
        }
        surface = {"surface_type": surface_names.get(surface_code, "other")}
        try:
            if surface_code == 1:
                surface["radius"] = round(float(adaptor.Cylinder().Radius()), 6)
            elif surface_code == 2:
                cone = adaptor.Cone()
                surface["reference_radius"] = round(float(cone.RefRadius()), 6)
                surface["semi_angle"] = round(float(cone.SemiAngle()), 6)
            elif surface_code == 3:
                surface["radius"] = round(float(adaptor.Sphere().Radius()), 6)
            elif surface_code == 4:
                torus = adaptor.Torus()
                surface["major_radius"] = round(float(torus.MajorRadius()), 6)
                surface["minor_radius"] = round(float(torus.MinorRadius()), 6)
        except (AttributeError, RuntimeError):
            pass
        face_index = len(face_surfaces)
        face_surfaces.append(surface)
        location = ocp["TopLoc_Location"]()
        triangulation = ocp["BRep_Tool"].Triangulation_s(face, location)
        if triangulation is not None:
            offset = len(vertices)
            transform = location.Transformation()
            vertices.extend(
                triangulation.Node(index).Transformed(transform).Coord()
                for index in range(1, triangulation.NbNodes() + 1)
            )
            reversed_face = face.Orientation() == ocp["TopAbs_REVERSED"]
            for index in range(1, triangulation.NbTriangles() + 1):
                triangle = list(triangulation.Triangle(index).Get())
                if reversed_face:
                    triangle[1], triangle[2] = triangle[2], triangle[1]
                triangles.append([offset + node - 1 for node in triangle])
                triangle_face_indices.append(face_index)
        explorer.Next()
    if not triangles:
        raise ValueError(f"STEP geometry contains no triangulated faces: {path}")
    vertex_array = np.asarray(vertices)
    triangle_array = np.asarray(triangles)
    face_index_array = np.asarray(triangle_face_indices, dtype=np.int64)
    descriptors = {}
    face_ids = np.empty(len(triangle_array), dtype="<U24")
    used_ids: dict[str, int] = {}
    for face_index, surface in enumerate(face_surfaces):
        selected = np.flatnonzero(face_index_array == face_index)
        if not len(selected):
            continue
        face_triangles = vertex_array[triangle_array[selected]]
        cross = np.cross(
            face_triangles[:, 1] - face_triangles[:, 0],
            face_triangles[:, 2] - face_triangles[:, 0],
        )
        areas = np.linalg.norm(cross, axis=1) / 2.0
        total_area = float(areas.sum())
        centroids = face_triangles.mean(axis=1)
        centroid = (
            (centroids * areas[:, None]).sum(axis=0) / total_area
            if total_area > 0 else centroids.mean(axis=0)
        )
        descriptor = {
            **surface,
            "area": round(total_area, 6),
            "centroid": [round(float(value), 6) for value in centroid],
            "bbox_min": [round(float(value), 6) for value in face_triangles.min(axis=(0, 1))],
            "bbox_max": [round(float(value), 6) for value in face_triangles.max(axis=(0, 1))],
        }
        canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
        base_id = "face-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        collision = used_ids.get(base_id, 0)
        used_ids[base_id] = collision + 1
        face_id = base_id if collision == 0 else f"{base_id}-{collision + 1}"
        descriptor["face_id"] = face_id
        descriptors[face_id] = descriptor
        face_ids[selected] = face_id
    return trimesh.Trimesh(
        vertices=vertex_array,
        faces=triangle_array,
        face_attributes={"brep_face_id": face_ids},
        metadata={"brep_face_descriptors": descriptors, "source_format": "step"},
        process=True,
    )


def _load_mesh(path: Path, *, tessellation: float = 0.05):
    ocp, np, _, trimesh = _dependencies()
    suffix = path.suffix.casefold()
    if suffix in {".step", ".stp"}:
        mesh = _load_step_mesh(
            path,
            tessellation=tessellation,
            ocp=ocp,
            np=np,
            trimesh=trimesh,
        )
    elif suffix in {".stl", ".obj", ".ply"}:
        mesh = trimesh.load_mesh(path, process=True)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh()
    else:
        raise ValueError(f"Unsupported geometry format: {path.suffix}")
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError(f"Geometry contains no triangles: {path}")
    return mesh


def _axis_rotations(np) -> list[Any]:
    rotations = []
    identity = np.eye(3)
    for permutation in itertools.permutations(range(3)):
        base = identity[:, permutation]
        for signs in itertools.product((-1.0, 1.0), repeat=3):
            matrix = base @ np.diag(signs)
            if np.linalg.det(matrix) > 0.5:
                rotations.append(matrix)
    return rotations


def _surface_samples(mesh, count: int, np):
    triangles = mesh.triangles
    areas = mesh.area_faces
    probabilities = areas / areas.sum()
    rng = np.random.default_rng(20260830)
    selected = rng.choice(len(triangles), size=count, p=probabilities)
    chosen = triangles[selected]
    uv = rng.random((count, 2))
    folded = uv.sum(axis=1) > 1.0
    uv[folded] = 1.0 - uv[folded]
    return (
        chosen[:, 0]
        + uv[:, :1] * (chosen[:, 1] - chosen[:, 0])
        + uv[:, 1:] * (chosen[:, 2] - chosen[:, 0])
    )


def _chamfer(candidate, target, cKDTree, np) -> float:
    forward = cKDTree(target).query(candidate, workers=-1)[0].mean()
    backward = cKDTree(candidate).query(target, workers=-1)[0].mean()
    return float((forward + backward) / 2.0)


def _distance_diagnostics(candidate, ground_truth, sample_count: int, cKDTree, np):
    _, _, _, trimesh = _dependencies()
    localization = localize_surface_mismatch(
        candidate,
        ground_truth,
        sample_count=sample_count,
        cKDTree=cKDTree,
        np=np,
        trimesh=trimesh,
    )
    summaries = localization.pop("distance_summary")
    return {**summaries, "localization": localization}


def _threshold_score(value: float, threshold: float) -> float:
    return max(0.0, min(1.0, 2.0 - value / threshold))


def geometry_quality_score(metrics: dict[str, Any], *, watertight: bool) -> float:
    """Return a continuous progress score without replacing strict passage."""
    score = 0.0
    score += 35.0 * max(0.0, min(1.0, metrics["voxel_iou"] / DEFAULT_THRESHOLDS["voxel_iou_min"]))
    score += 25.0 * _threshold_score(
        metrics["normalized_chamfer"], DEFAULT_THRESHOLDS["normalized_chamfer_max"],
    )
    score += 15.0 * _threshold_score(
        metrics["bbox_relative_error"], DEFAULT_THRESHOLDS["bbox_relative_error_max"],
    )
    score += 20.0 * _threshold_score(
        metrics["volume_relative_error"], DEFAULT_THRESHOLDS["volume_relative_error_max"],
    )
    score += 5.0 if watertight else 0.0
    return round(score, 2)


def _aligned_candidate(candidate, ground_truth, sample_count: int):
    _, np, cKDTree, _ = _dependencies()
    candidate_points = _surface_samples(candidate, sample_count, np)
    target_points = _surface_samples(ground_truth, sample_count, np)
    candidate_center = candidate.bounds.mean(axis=0)
    target_center = ground_truth.bounds.mean(axis=0)
    best = None
    for rotation in _axis_rotations(np):
        points = (candidate_points - candidate_center) @ rotation.T + target_center
        distance = _chamfer(points, target_points, cKDTree, np)
        if best is None or distance < best[0]:
            best = (distance, rotation)
    assert best is not None
    aligned = candidate.copy()
    aligned.vertices = (aligned.vertices - candidate_center) @ best[1].T + target_center
    return aligned, best[0], best[1]


def _voxel_keys(mesh, pitch: float, origin, np) -> set[tuple[int, int, int]]:
    points = mesh.voxelized(pitch).fill().points
    indices = np.rint((points - origin) / pitch).astype(np.int64)
    return {tuple(row) for row in indices.tolist()}


def score_geometry_files(
    candidate_path: str | Path,
    ground_truth_path: str | Path,
    *,
    sample_count: int = 20000,
    voxel_resolution: int = 64,
) -> dict[str, Any]:
    if sample_count <= 0 or voxel_resolution < 16:
        raise ValueError("sample_count must be positive and voxel_resolution must be at least 16")
    _, np, cKDTree, _ = _dependencies()
    candidate_path = Path(candidate_path).resolve()
    ground_truth_path = Path(ground_truth_path).resolve()
    if not candidate_path.is_file() or not ground_truth_path.is_file():
        raise FileNotFoundError(candidate_path if not candidate_path.is_file() else ground_truth_path)
    candidate = _load_mesh(candidate_path)
    ground_truth = _load_mesh(ground_truth_path)
    aligned, chamfer, rotation = _aligned_candidate(candidate, ground_truth, sample_count)
    diagonal = float(np.linalg.norm(ground_truth.extents))
    if diagonal <= 0:
        raise ValueError("Ground-truth geometry has a zero bounding-box diagonal")
    pitch = diagonal / voxel_resolution
    origin = np.minimum(aligned.bounds[0], ground_truth.bounds[0]) - pitch * 2
    candidate_voxels = _voxel_keys(aligned, pitch, origin, np)
    truth_voxels = _voxel_keys(ground_truth, pitch, origin, np)
    union = candidate_voxels | truth_voxels
    voxel_iou = len(candidate_voxels & truth_voxels) / len(union) if union else 0.0
    bbox_error = float(np.mean(np.abs(aligned.extents - ground_truth.extents) / np.maximum(
        np.abs(ground_truth.extents), diagonal * 1e-6,
    )))
    volume_error = abs(float(aligned.volume) - float(ground_truth.volume)) / max(
        abs(float(ground_truth.volume)), diagonal ** 3 * 1e-9,
    )
    area_error = abs(float(aligned.area) - float(ground_truth.area)) / max(
        abs(float(ground_truth.area)), diagonal ** 2 * 1e-9,
    )
    normalized_chamfer = chamfer / diagonal
    metrics = {
        "voxel_iou": round(float(voxel_iou), 6),
        "chamfer_distance": round(float(chamfer), 6),
        "normalized_chamfer": round(float(normalized_chamfer), 6),
        "bbox_relative_error": round(float(bbox_error), 6),
        "volume_relative_error": round(float(volume_error), 6),
        "surface_area_relative_error": round(float(area_error), 6),
    }
    checks = {
        "candidate_watertight": bool(aligned.is_watertight),
        "voxel_iou": voxel_iou >= DEFAULT_THRESHOLDS["voxel_iou_min"],
        "normalized_chamfer": normalized_chamfer <= DEFAULT_THRESHOLDS["normalized_chamfer_max"],
        "bbox_relative_error": bbox_error <= DEFAULT_THRESHOLDS["bbox_relative_error_max"],
        "volume_relative_error": volume_error <= DEFAULT_THRESHOLDS["volume_relative_error_max"],
    }
    acceptable_checks = {
        "candidate_watertight": bool(aligned.is_watertight),
        "voxel_iou": voxel_iou >= ACCEPTABLE_THRESHOLDS["voxel_iou_min"],
        "normalized_chamfer": normalized_chamfer <= ACCEPTABLE_THRESHOLDS["normalized_chamfer_max"],
        "bbox_relative_error": bbox_error <= ACCEPTABLE_THRESHOLDS["bbox_relative_error_max"],
        "volume_relative_error": volume_error <= ACCEPTABLE_THRESHOLDS["volume_relative_error_max"],
    }
    quality_tier = "strict" if all(checks.values()) else (
        "acceptable" if all(acceptable_checks.values()) else "failed"
    )
    return {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "candidate": str(candidate_path),
        "ground_truth": str(ground_truth_path),
        "passed": all(checks.values()),
        "quality_tier": quality_tier,
        "score": geometry_quality_score(metrics, watertight=bool(aligned.is_watertight)),
        "coverage": 100.0,
        "checks": checks,
        "acceptable_checks": acceptable_checks,
        "alignment": {
            "type": "right-handed-axis-permutation-plus-translation",
            "rotation": rotation.round(6).tolist(),
            "scale_allowed": False,
        },
        "metrics": metrics,
        "mismatch": _distance_diagnostics(
            aligned, ground_truth, sample_count, cKDTree, np,
        ),
        "candidate_geometry": {
            "vertices": int(len(aligned.vertices)),
            "triangles": int(len(aligned.faces)),
            "watertight": bool(aligned.is_watertight),
            "volume": round(float(aligned.volume), 6),
            "surface_area": round(float(aligned.area), 6),
            "extents": aligned.extents.round(6).tolist(),
        },
        "ground_truth_geometry": {
            "vertices": int(len(ground_truth.vertices)),
            "triangles": int(len(ground_truth.faces)),
            "watertight": bool(ground_truth.is_watertight),
            "volume": round(float(ground_truth.volume), 6),
            "surface_area": round(float(ground_truth.area), 6),
            "extents": ground_truth.extents.round(6).tolist(),
        },
        "parameters": {
            "surface_samples": sample_count,
            "voxel_resolution": voxel_resolution,
            "voxel_pitch": round(float(pitch), 6),
            "thresholds": DEFAULT_THRESHOLDS,
            "acceptable_thresholds": ACCEPTABLE_THRESHOLDS,
        },
    }


def calibrate_geometry_manifest(
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    sample_count: int = 20000,
    voxel_resolution: int = 48,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    output_path = Path(output_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for sample in manifest.get("samples", []):
        if not sample.get("ground_truth_stl") or not sample.get("ground_truth_step"):
            continue
        result = score_geometry_files(
            manifest_path.parent / sample["ground_truth_stl"],
            manifest_path.parent / sample["ground_truth_step"],
            sample_count=sample_count,
            voxel_resolution=voxel_resolution,
        )
        mismatch = result.get("mismatch") or {}
        localization = mismatch.get("localization") or {}
        rows.append({
            "sample_id": sample["sample_id"],
            "dataset": sample["dataset"],
            "passed": result["passed"],
            "checks": result["checks"],
            "metrics": result["metrics"],
            "localization": {
                "region_count": localization.get("region_count"),
                "localized_sample_fraction": localization.get("localized_sample_fraction"),
                "candidate_to_ground_truth_p95_normalized": (
                    (mismatch.get("candidate_to_ground_truth") or {}).get("p95_normalized")
                ),
                "candidate_to_ground_truth_max_normalized": (
                    (mismatch.get("candidate_to_ground_truth") or {}).get("max_normalized")
                ),
                "ground_truth_to_candidate_p95_normalized": (
                    (mismatch.get("ground_truth_to_candidate") or {}).get("p95_normalized")
                ),
                "ground_truth_to_candidate_max_normalized": (
                    (mismatch.get("ground_truth_to_candidate") or {}).get("max_normalized")
                ),
            } if mismatch else None,
        })
    metrics = [row["metrics"] for row in rows]
    localization_rows = [row["localization"] for row in rows if row["localization"]]
    summary = {
        "pairs": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "mean_voxel_iou": round(statistics.mean(
            item["voxel_iou"] for item in metrics
        ), 6) if metrics else None,
        "mean_normalized_chamfer": round(statistics.mean(
            item["normalized_chamfer"] for item in metrics
        ), 6) if metrics else None,
        "mean_volume_relative_error": round(statistics.mean(
            item["volume_relative_error"] for item in metrics
        ), 6) if metrics else None,
        "localization_false_region_pairs": sum(
            int(item["region_count"] or 0) > 0 for item in localization_rows
        ),
        "maximum_localization_p95_normalized": round(max((
            max(
                float(item["candidate_to_ground_truth_p95_normalized"] or 0),
                float(item["ground_truth_to_candidate_p95_normalized"] or 0),
            )
            for item in localization_rows
        ), default=0.0), 6),
        "maximum_localization_distance_normalized": round(max((
            max(
                float(item["candidate_to_ground_truth_max_normalized"] or 0),
                float(item["ground_truth_to_candidate_max_normalized"] or 0),
            )
            for item in localization_rows
        ), default=0.0), 6),
    }
    payload = {
        "schema_version": "1.0",
        "kind": "ground-truth-cross-format-calibration",
        "protocol": PROTOCOL_ID,
        "manifest": (
            manifest_path.relative_to(Path.cwd().resolve()).as_posix()
            if manifest_path.is_relative_to(Path.cwd().resolve()) else str(manifest_path)
        ),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "parameters": {
            "surface_samples": sample_count,
            "voxel_resolution": voxel_resolution,
            "thresholds": DEFAULT_THRESHOLDS,
        },
        "summary": summary,
        "results": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
