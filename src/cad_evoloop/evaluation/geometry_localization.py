"""Deterministic surface-error localization for aligned triangle meshes."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any


LOCALIZATION_PROTOCOL_ID = "evocad-surface-localization-v1"
DEFAULT_DISTANCE_THRESHOLD_NORMALIZED = 0.006
DEFAULT_CLUSTER_RADIUS_NORMALIZED = 0.025
DEFAULT_MAX_REGIONS = 12


def _surface_samples(mesh, count: int, np):
    triangles = mesh.triangles
    areas = mesh.area_faces
    total_area = float(areas.sum())
    if total_area <= 0:
        raise ValueError("Cannot localize a mesh with zero surface area")
    rng = np.random.default_rng(20260902)
    selected = rng.choice(len(triangles), size=count, p=areas / total_area)
    chosen = triangles[selected]
    uv = rng.random((count, 2))
    folded = uv.sum(axis=1) > 1.0
    uv[folded] = 1.0 - uv[folded]
    points = (
        chosen[:, 0]
        + uv[:, :1] * (chosen[:, 1] - chosen[:, 0])
        + uv[:, 1:] * (chosen[:, 2] - chosen[:, 0])
    )
    face_ids = mesh.face_attributes.get("brep_face_id")
    selected_face_ids = face_ids[selected] if face_ids is not None else None
    descriptors = mesh.metadata.get("brep_face_descriptors", {})
    return points, mesh.face_normals[selected], selected, selected_face_ids, descriptors


def _cell_components(points, radius: float, np) -> list[Any]:
    """Cluster points through connected occupied spatial cells in linear memory."""
    cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    coordinates = np.floor(points / radius).astype(np.int64)
    for index, coordinate in enumerate(coordinates):
        cells[tuple(int(value) for value in coordinate)].append(index)

    occupied = set(cells)
    visited: set[tuple[int, int, int]] = set()
    components = []
    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if (dx, dy, dz) != (0, 0, 0)
    ]
    for start in sorted(occupied):
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        indices = []
        while stack:
            cell = stack.pop()
            indices.extend(cells[cell])
            for offset in offsets:
                neighbor = tuple(cell[axis] + offset[axis] for axis in range(3))
                if neighbor in occupied and neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        components.append(np.asarray(indices, dtype=np.int64))
    return components


def _round_vector(value, digits: int = 6) -> list[float]:
    return [round(float(item), digits) for item in value]


def _closest_surface(points, mesh, *, cKDTree, np, trimesh):
    """Return exact point-to-triangle distances with a centroid-radius index.

    For a triangle with centroid ``c`` and enclosing radius ``r``, its distance
    from point ``p`` is bounded below by ``max(||p-c||-r, 0)``. Querying every
    radius bin out to the current best distance plus that bin's maximum radius
    therefore cannot omit a closer triangle.
    """
    triangles = mesh.triangles
    centroids = triangles.mean(axis=1)
    radii = np.linalg.norm(triangles - centroids[:, None, :], axis=2).max(axis=1)
    tree = cKDTree(centroids)
    initial_k = min(8, len(triangles))
    _, initial = tree.query(points, k=initial_k, workers=-1)
    if initial_k == 1:
        initial = initial[:, None]
    repeated_points = np.repeat(points, initial_k, axis=0)
    initial_triangles = initial.reshape(-1)
    closest = trimesh.triangles.closest_point(
        triangles[initial_triangles], repeated_points,
    ).reshape(len(points), initial_k, 3)
    initial_distances = np.linalg.norm(closest - points[:, None, :], axis=2)
    best_column = np.argmin(initial_distances, axis=1)
    rows = np.arange(len(points))
    best_distances = initial_distances[rows, best_column]
    best_faces = initial[rows, best_column].astype(np.int64)
    best_points = closest[rows, best_column]

    positive = radii[radii > 0]
    minimum_radius = max(float(positive.min()) if len(positive) else 1.0, 1e-12)
    buckets: dict[int, list[int]] = defaultdict(list)
    for index, radius in enumerate(radii):
        bucket = int(math.floor(math.log2(max(float(radius), minimum_radius) / minimum_radius)))
        buckets[bucket].append(index)
    batch_size = 512
    for bucket in sorted(buckets):
        face_indices = np.asarray(buckets[bucket], dtype=np.int64)
        bucket_tree = cKDTree(centroids[face_indices])
        maximum_radius = float(radii[face_indices].max())
        for start in range(0, len(points), batch_size):
            stop = min(start + batch_size, len(points))
            candidates = bucket_tree.query_ball_point(
                points[start:stop],
                r=best_distances[start:stop] + maximum_radius,
                workers=-1,
            )
            for offset, local_indices in enumerate(candidates):
                if not local_indices:
                    continue
                point_index = start + offset
                global_indices = face_indices[np.asarray(local_indices, dtype=np.int64)]
                query_points = np.repeat(points[point_index][None, :], len(global_indices), axis=0)
                candidate_points = trimesh.triangles.closest_point(
                    triangles[global_indices], query_points,
                )
                candidate_distances = np.linalg.norm(
                    candidate_points - points[point_index], axis=1,
                )
                winner = int(np.argmin(candidate_distances))
                if candidate_distances[winner] < best_distances[point_index]:
                    best_distances[point_index] = candidate_distances[winner]
                    best_faces[point_index] = global_indices[winner]
                    best_points[point_index] = candidate_points[winner]
    return best_distances, best_points, best_faces


def _direction_regions(
    *,
    source_points,
    source_normals,
    target_mesh,
    source_face_ids,
    source_face_descriptors,
    source_area: float,
    direction: str,
    error_type: str,
    diagonal: float,
    truth_lower,
    truth_extents,
    threshold: float,
    cluster_radius: float,
    cKDTree,
    np,
    trimesh,
) -> tuple[list[dict[str, Any]], dict[int, Any], Any, Any]:
    distances, nearest_points, nearest_faces = _closest_surface(
        source_points, target_mesh, cKDTree=cKDTree, np=np, trimesh=trimesh,
    )
    outlier_indices = np.flatnonzero(distances > threshold)
    if not len(outlier_indices):
        return [], {}, distances, nearest_faces

    outlier_points = source_points[outlier_indices]
    components = _cell_components(outlier_points, cluster_radius, np)
    minimum_samples = max(8, int(math.ceil(len(source_points) / 5000)))
    candidates = []
    for component in components:
        if len(component) < minimum_samples:
            continue
        sample_indices = outlier_indices[component]
        region_points = source_points[sample_indices]
        region_distances = distances[sample_indices]
        nearest_normals = target_mesh.face_normals[nearest_faces[sample_indices]]
        normal_agreement = np.abs(np.einsum(
            "ij,ij->i", source_normals[sample_indices], nearest_normals,
        ))
        normal_offsets = np.einsum(
            "ij,ij->i",
            region_points - nearest_points[sample_indices],
            nearest_normals,
        )
        centroid = region_points.mean(axis=0)
        lower = region_points.min(axis=0)
        upper = region_points.max(axis=0)
        dominant_normal = source_normals[sample_indices].mean(axis=0)
        norm = float(np.linalg.norm(dominant_normal))
        if norm > 1e-12:
            dominant_normal /= norm
        p95 = float(np.quantile(region_distances, 0.95))
        fraction = len(sample_indices) / len(source_points)
        candidates.append({
            "direction": direction,
            "error_type": error_type,
            "sample_count": int(len(sample_indices)),
            "sample_fraction": round(float(fraction), 6),
            "estimated_area": round(float(source_area * fraction), 6),
            "estimated_area_fraction": round(float(fraction), 6),
            "centroid": _round_vector(centroid),
            "centroid_bbox_position": _round_vector(
                (centroid - truth_lower) / truth_extents, 4,
            ),
            "bbox": {
                "min": _round_vector(lower),
                "max": _round_vector(upper),
            },
            "mean_distance_normalized": round(float(region_distances.mean() / diagonal), 6),
            "p95_distance_normalized": round(float(p95 / diagonal), 6),
            "max_distance_normalized": round(float(region_distances.max() / diagonal), 6),
            "mean_normal_offset_normalized": round(
                float(normal_offsets.mean() / diagonal), 6,
            ),
            "mean_normal_disagreement": round(float((1.0 - normal_agreement).mean()), 6),
            "dominant_source_normal": _round_vector(dominant_normal, 4),
            "confidence": (
                "high" if len(sample_indices) >= 25 and p95 >= threshold * 1.5
                else "medium" if len(sample_indices) >= 8
                else "low"
            ),
            "source_surface_query_points": [
                _round_vector(region_points[index])
                for index in np.linspace(
                    0, len(region_points) - 1, min(9, len(region_points)), dtype=np.int64,
                )
            ],
            "_sample_indices": sample_indices,
            "_rank": float(p95 / diagonal) * math.sqrt(len(sample_indices)),
        })
        if source_face_ids is not None:
            identifiers, counts = np.unique(source_face_ids[sample_indices], return_counts=True)
            order = np.argsort(counts)[::-1]
            candidates[-1]["source_brep_faces"] = [{
                "face_id": str(identifiers[index]),
                "sample_fraction": round(float(counts[index] / len(sample_indices)), 6),
                "surface_type": source_face_descriptors.get(
                    str(identifiers[index]), {},
                ).get("surface_type", "unknown"),
                **{
                    key: value
                    for key, value in source_face_descriptors.get(
                        str(identifiers[index]), {},
                    ).items()
                    if key in {
                        "radius", "reference_radius", "semi_angle",
                        "major_radius", "minor_radius",
                    }
                },
            } for index in order[:5]]
    candidates.sort(key=lambda item: (-item["_rank"], item["centroid"]))
    regions = candidates[:DEFAULT_MAX_REGIONS]
    index_map = {}
    prefix = "excess" if direction == "candidate_to_ground_truth" else "missing"
    for number, region in enumerate(regions, start=1):
        region_id = f"{prefix}-{number:02d}"
        region["region_id"] = region_id
        index_map.update({int(index): region_id for index in region.pop("_sample_indices")})
        region.pop("_rank")
    return regions, index_map, distances, nearest_faces


def _link_counterparts(regions: list[dict[str, Any]], diagonal: float, np) -> None:
    excess = [item for item in regions if item["direction"] == "candidate_to_ground_truth"]
    missing = [item for item in regions if item["direction"] == "ground_truth_to_candidate"]
    maximum_gap = diagonal * DEFAULT_CLUSTER_RADIUS_NORMALIZED * 2.0
    for first in excess:
        first_center = np.asarray(first["centroid"], dtype=float)
        matches = []
        for second in missing:
            distance = float(np.linalg.norm(first_center - np.asarray(second["centroid"], dtype=float)))
            if distance <= maximum_gap:
                matches.append((distance, second["region_id"]))
        if matches:
            matches.sort()
            first["counterpart_region_ids"] = [item[1] for item in matches[:3]]
    reverse = defaultdict(list)
    for first in excess:
        for identifier in first.get("counterpart_region_ids", []):
            reverse[identifier].append(first["region_id"])
    for second in missing:
        if reverse[second["region_id"]]:
            second["counterpart_region_ids"] = reverse[second["region_id"]][:3]


def _visualization_points(
    points,
    distances,
    region_by_sample: dict[int, str],
    *,
    diagonal: float,
    maximum: int,
    np,
) -> list[dict[str, Any]]:
    if not region_by_sample or maximum <= 0:
        return []
    grouped: dict[str, list[int]] = defaultdict(list)
    for sample_index, region_id in region_by_sample.items():
        grouped[region_id].append(sample_index)
    selected = []
    region_count = len(grouped)
    quota = max(8, maximum // max(region_count, 1))
    for region_id in sorted(grouped):
        indices = np.asarray(grouped[region_id], dtype=np.int64)
        ordered = indices[np.argsort(distances[indices])[::-1]]
        if len(ordered) > quota:
            positions = np.linspace(0, len(ordered) - 1, quota, dtype=np.int64)
            ordered = ordered[positions]
        selected.extend((int(index), region_id) for index in ordered)
    selected.sort(key=lambda item: (-float(distances[item[0]]), item[1], item[0]))
    return [{
        "point": _round_vector(points[index]),
        "distance_normalized": round(float(distances[index] / diagonal), 6),
        "region_id": region_id,
    } for index, region_id in selected[:maximum]]


def localize_surface_mismatch(
    candidate,
    ground_truth,
    *,
    sample_count: int,
    cKDTree,
    np,
    trimesh,
    include_visualization: bool = False,
    max_visualization_points: int = 1200,
) -> dict[str, Any]:
    """Locate high-error connected surface patches in an aligned coordinate frame."""
    diagonal = float(np.linalg.norm(ground_truth.extents))
    if diagonal <= 0:
        raise ValueError("Ground-truth geometry has a zero bounding-box diagonal")
    truth_lower = ground_truth.bounds[0]
    truth_extents = np.maximum(ground_truth.extents, diagonal * 1e-9)
    threshold = diagonal * DEFAULT_DISTANCE_THRESHOLD_NORMALIZED
    cluster_radius = diagonal * DEFAULT_CLUSTER_RADIUS_NORMALIZED
    (
        candidate_points, candidate_normals, _, candidate_face_ids,
        candidate_face_descriptors,
    ) = _surface_samples(candidate, sample_count, np)
    (
        truth_points, truth_normals, _, truth_face_ids, truth_face_descriptors,
    ) = _surface_samples(ground_truth, sample_count, np)

    excess, excess_map, candidate_distances, _ = _direction_regions(
        source_points=candidate_points,
        source_normals=candidate_normals,
        target_mesh=ground_truth,
        source_face_ids=candidate_face_ids,
        source_face_descriptors=candidate_face_descriptors,
        source_area=float(candidate.area),
        direction="candidate_to_ground_truth",
        error_type="candidate_excess_or_displaced_surface",
        diagonal=diagonal,
        truth_lower=truth_lower,
        truth_extents=truth_extents,
        threshold=threshold,
        cluster_radius=cluster_radius,
        cKDTree=cKDTree,
        np=np,
        trimesh=trimesh,
    )
    missing, missing_map, truth_distances, _ = _direction_regions(
        source_points=truth_points,
        source_normals=truth_normals,
        target_mesh=candidate,
        source_face_ids=truth_face_ids,
        source_face_descriptors=truth_face_descriptors,
        source_area=float(ground_truth.area),
        direction="ground_truth_to_candidate",
        error_type="candidate_missing_or_displaced_surface",
        diagonal=diagonal,
        truth_lower=truth_lower,
        truth_extents=truth_extents,
        threshold=threshold,
        cluster_radius=cluster_radius,
        cKDTree=cKDTree,
        np=np,
        trimesh=trimesh,
    )
    regions = [*excess, *missing]
    _link_counterparts(regions, diagonal, np)
    outlier_count = len(excess_map) + len(missing_map)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol": LOCALIZATION_PROTOCOL_ID,
        "coordinate_frame": "aligned-ground-truth-world",
        "uses_evaluator_ground_truth": True,
        "interpretation": (
            "Directional sampled-surface evidence. Regions localize discrepancies but do not "
            "by themselves identify CAD feature semantics or the responsible modeling operation."
        ),
        "distance_threshold_normalized": DEFAULT_DISTANCE_THRESHOLD_NORMALIZED,
        "cluster_radius_normalized": DEFAULT_CLUSTER_RADIUS_NORMALIZED,
        "surface_samples_per_direction": sample_count,
        "localized_sample_fraction": round(
            float(outlier_count / (sample_count * 2)), 6,
        ),
        "region_count": len(regions),
        "regions": regions,
        "distance_summary": {
            "candidate_to_ground_truth": {
                "p50_normalized": round(float(np.quantile(candidate_distances, 0.5) / diagonal), 6),
                "p95_normalized": round(float(np.quantile(candidate_distances, 0.95) / diagonal), 6),
                "max_normalized": round(float(candidate_distances.max() / diagonal), 6),
                "worst_point_bbox_position": _round_vector(
                    (candidate_points[int(np.argmax(candidate_distances))] - truth_lower)
                    / truth_extents,
                    4,
                ),
            },
            "ground_truth_to_candidate": {
                "p50_normalized": round(float(np.quantile(truth_distances, 0.5) / diagonal), 6),
                "p95_normalized": round(float(np.quantile(truth_distances, 0.95) / diagonal), 6),
                "max_normalized": round(float(truth_distances.max() / diagonal), 6),
                "worst_point_bbox_position": _round_vector(
                    (truth_points[int(np.argmax(truth_distances))] - truth_lower)
                    / truth_extents,
                    4,
                ),
            },
        },
    }
    if include_visualization:
        per_direction = max(1, max_visualization_points // 2)
        payload["visualization"] = {
            "candidate_to_ground_truth": _visualization_points(
                candidate_points,
                candidate_distances,
                excess_map,
                diagonal=diagonal,
                maximum=per_direction,
                np=np,
            ),
            "ground_truth_to_candidate": _visualization_points(
                truth_points,
                truth_distances,
                missing_map,
                diagonal=diagonal,
                maximum=per_direction,
                np=np,
            ),
        }
    return payload
