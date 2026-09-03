"""Map localized mesh discrepancies to native CAD topology and feature candidates."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
from pathlib import Path
import json
from typing import Any, Iterable


FEATURE_PROTOCOL_ID = "evocad-native-feature-localization-v1"
BOOLEAN_LINEAGE_PROTOCOL_ID = "evocad-boolean-face-lineage-v2"


def _vector(value: Iterable[float]) -> tuple[float, float, float]:
    result = tuple(float(item) for item in value)
    if len(result) != 3:
        raise ValueError("Expected a three-dimensional vector")
    return result  # type: ignore[return-value]


def _corners(bounds: dict[str, Any]) -> list[tuple[float, float, float]]:
    lower, upper = _vector(bounds["min"]), _vector(bounds["max"])
    return [
        (x, y, z)
        for x in (lower[0], upper[0])
        for y in (lower[1], upper[1])
        for z in (lower[2], upper[2])
    ]


def _aligned_bounds(
    bounds: dict[str, Any], candidate_center, truth_center, rotation,
) -> dict[str, list[float]]:
    points = []
    for corner in _corners(bounds):
        relative = [corner[index] - candidate_center[index] for index in range(3)]
        point = [
            sum(rotation[row][column] * relative[column] for column in range(3))
            + truth_center[row]
            for row in range(3)
        ]
        points.append(point)
    return {
        "min": [min(point[index] for point in points) for index in range(3)],
        "max": [max(point[index] for point in points) for index in range(3)],
    }


def _bbox_distance(first: dict[str, Any], second: dict[str, Any]) -> float:
    lower_a, upper_a = _vector(first["min"]), _vector(first["max"])
    lower_b, upper_b = _vector(second["min"]), _vector(second["max"])
    gaps = [max(lower_a[i] - upper_b[i], lower_b[i] - upper_a[i], 0.0) for i in range(3)]
    return math.sqrt(sum(value * value for value in gaps))


def _bbox_overlap(first: dict[str, Any], second: dict[str, Any]) -> float:
    lower_a, upper_a = _vector(first["min"]), _vector(first["max"])
    lower_b, upper_b = _vector(second["min"]), _vector(second["max"])
    intersection = math.prod(max(0.0, min(upper_a[i], upper_b[i]) - max(lower_a[i], lower_b[i])) for i in range(3))
    volume_a = math.prod(max(upper_a[i] - lower_a[i], 1e-12) for i in range(3))
    volume_b = math.prod(max(upper_b[i] - lower_b[i], 1e-12) for i in range(3))
    return intersection / min(volume_a, volume_b)


def build_feature_graph(topology: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic face adjacency and conservative engineering feature candidates."""
    nodes: list[dict[str, Any]] = []
    graph_edges: set[tuple[str, str]] = set()
    feature_candidates: list[dict[str, Any]] = []
    for entity in topology.get("entities", []):
        handle = str(entity.get("handle", ""))
        faces = {str(face["id"]): face for face in entity.get("faces", [])}
        for edge in entity.get("edges", []):
            identifiers = sorted(str(item) for item in edge.get("face_ids", []))
            for index, first in enumerate(identifiers):
                for second in identifiers[index + 1:]:
                    graph_edges.add((f"{handle}:{first}", f"{handle}:{second}"))
        for face_id, face in faces.items():
            node_id = f"{handle}:{face_id}"
            surface = face.get("surface") or {}
            nodes.append({
                "node_id": node_id,
                "entity_handle": handle,
                "face_id": face_id,
                "face_fingerprint": face.get("fingerprint"),
                "surface_type": surface.get("type", "unknown"),
                "area": face.get("area"),
                "bounds": face.get("bounds"),
                "edge_count": len(face.get("edge_ids", [])),
            })
            surface_type = str(surface.get("type", "")).casefold()
            if surface_type in {"cylinder", "cone", "sphere", "torus"}:
                if surface_type == "cylinder":
                    outward_from_axis = bool(surface.get("outer_normal")) == bool(
                        face.get("orientation_to_surface", True)
                    )
                    kind = "boss_candidate" if outward_from_axis else "hole_candidate"
                else:
                    kind = f"{surface_type}_surface_candidate"
                feature_candidates.append({
                    "feature_id": f"feature-{handle}-{face_id}",
                    "kind": kind,
                    "confidence": "medium" if surface_type == "cylinder" else "low",
                    "entity_handle": handle,
                    "face_ids": [face_id],
                    "face_fingerprints": [face.get("fingerprint")],
                    "parameters": {
                        key: surface[key]
                        for key in ("radius", "base_radius", "half_angle", "major_radius", "minor_radius", "axis", "origin", "center")
                        if key in surface
                    },
                    "interpretation": "Candidate inferred from analytic surface orientation; verify against the drawing and adjacent faces.",
                })
    return {
        "schema_version": "1.0",
        "protocol": FEATURE_PROTOCOL_ID,
        "nodes": nodes,
        "edges": [{"source": first, "target": second, "relation": "shares_brep_edge"} for first, second in sorted(graph_edges)],
        "feature_candidates": feature_candidates,
    }


def _topology_faces(topology: dict[str, Any] | None) -> list[dict[str, Any]]:
    records = []
    for entity in (topology or {}).get("entities", []):
        handle = str(entity.get("handle", ""))
        for face in entity.get("faces", []):
            records.append({
                "node_id": f"{handle}:{face.get('id')}",
                "entity_handle": handle,
                "face_id": str(face.get("id", "")),
                "face_fingerprint": face.get("fingerprint"),
            })
    return records


def _topology_signature(topology: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(
        str(face.get("face_fingerprint") or "") for face in _topology_faces(topology)
    ))


def _captured_history_face_lineage(
    topology: dict[str, Any], operations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, int]:
    """Propagate face origins through every captured Core Console job and branch."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for operation in operations:
        job_id = operation.get("mcp_job_id")
        before_path = operation.get("topology_before_path")
        after_path = operation.get("topology_after_path")
        if job_id and before_path and after_path:
            groups.setdefault(str(job_id), []).append(operation)

    states_by_output: dict[str, dict[str, dict[str, Any]]] = {}
    matching_state: dict[str, dict[str, Any]] | None = None
    captured = 0
    final_signature = _topology_signature(topology)
    for group in groups.values():
        before_path = Path(str(group[0]["topology_before_path"]))
        after_path = Path(str(group[0]["topology_after_path"]))
        if not before_path.is_file() or not after_path.is_file():
            continue
        try:
            before = json.loads(before_path.read_text(encoding="utf-8"))
            after = json.loads(after_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        captured += 1
        input_key = str(Path(str(group[0].get("input_path", ""))).resolve())
        output_key = str(Path(str(group[0].get("output_path", ""))).resolve())
        parent_state = states_by_output.get(input_key, {})
        before_fingerprints = {
            str(face.get("face_fingerprint") or "") for face in _topology_faces(before)
        }
        geometry_operations = [
            operation for operation in group
            if str(operation.get("operation_type", "")).casefold()
            not in {"validation", "verification", "inspection"}
        ] or group
        operation_ids = [str(operation["operation_id"]) for operation in geometry_operations]
        state = {}
        for face in _topology_faces(after):
            fingerprint = str(face.get("face_fingerprint") or "")
            prior = parent_state.get(fingerprint)
            if fingerprint in before_fingerprints:
                candidate_operations = list((prior or {}).get("candidate_operation_ids", []))
                evidence = list(dict.fromkeys([
                    *((prior or {}).get("evidence", [])), "stable_face_fingerprint_chain",
                ]))
                confidence = str((prior or {}).get("confidence", "high"))
                status = "inherited"
            else:
                candidate_operations = operation_ids
                evidence = ["topology_snapshot_delta", "captured_mcp_job"]
                confidence = "medium" if len(operation_ids) == 1 else "low"
                status = "created_or_modified"
            state[fingerprint] = {
                **face,
                "status": status,
                "parent_face_candidates": [],
                "candidate_operation_ids": candidate_operations,
                "evidence": evidence,
                "confidence": confidence,
                "origin_mcp_job_id": (
                    (prior or {}).get("origin_mcp_job_id")
                    if status == "inherited" else group[0].get("mcp_job_id")
                ),
            }
        states_by_output[output_key] = state
        if _topology_signature(after) == final_signature:
            matching_state = state

    if matching_state is None:
        return None, captured
    result = []
    for face in _topology_faces(topology):
        fingerprint = str(face.get("face_fingerprint") or "")
        lineage = matching_state.get(fingerprint)
        if lineage is None:
            return None, captured
        result.append({**lineage, **face})
    return result, captured


def build_boolean_face_lineage(
    topology: dict[str, Any],
    parent_topology: dict[str, Any] | None,
    operations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compare native topology snapshots and attach conservative operation ancestry."""
    current_faces = _topology_faces(topology)
    parent_faces = _topology_faces(parent_topology)
    operations = operations or []
    parent_by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for face in parent_faces:
        if face.get("face_fingerprint"):
            parent_by_fingerprint[str(face["face_fingerprint"])].append(face)

    operation_nodes = []
    operation_by_id = {}
    for index, operation in enumerate(operations):
        operation_id = str(operation.get("operation_id") or f"undeclared-{index + 1}")
        node = {
            "operation_id": operation_id,
            "intent": operation.get("intent"),
            "operation_type": operation.get("operation_type"),
            "feature_id": operation.get("feature_id"),
            "parameters": deepcopy(operation.get("parameters") or {}),
            "parent_operation_ids": [str(item) for item in operation.get("parent_operation_ids", [])],
            "mcp_job_id": operation.get("mcp_job_id"),
        }
        operation_nodes.append(node)
        operation_by_id[operation_id] = operation

    face_lineage = []
    inherited_fingerprints = set()
    for face in current_faces:
        fingerprint = str(face.get("face_fingerprint") or "")
        parents = parent_by_fingerprint.get(fingerprint, []) if fingerprint else []
        declared = [
            operation_id for operation_id, operation in operation_by_id.items()
            if fingerprint and fingerprint in {
                str(item) for item in operation.get("face_fingerprints", [])
            }
        ]
        if parents:
            inherited_fingerprints.add(fingerprint)
            status = "inherited"
            candidate_operations: list[str] = []
            evidence = ["stable_face_fingerprint"]
            confidence = "high" if len(parents) == 1 else "medium"
        else:
            status = "created_or_modified"
            if declared:
                candidate_operations = declared
                evidence = ["declared_face_fingerprint"]
                confidence = "high"
            else:
                handle_candidates = []
                for operation_id, operation in operation_by_id.items():
                    handles = {
                        str(item)
                        for key in ("target_entity_handles", "entity_handles", "observed_entity_handles")
                        for item in operation.get(key, [])
                    }
                    if face["entity_handle"] in handles:
                        handle_candidates.append(operation_id)
                candidate_operations = handle_candidates or list(operation_by_id)
                evidence = [
                    "topology_snapshot_delta",
                    "target_entity_handle" if handle_candidates else "mcp_job_operation_group",
                ]
                confidence = "medium" if len(candidate_operations) == 1 else "low"
        face_lineage.append({
            **face,
            "status": status,
            "parent_face_candidates": [item["node_id"] for item in parents],
            "candidate_operation_ids": candidate_operations,
            "evidence": evidence,
            "confidence": confidence,
        })

    history_lineage, captured_job_count = _captured_history_face_lineage(
        topology, operations,
    )
    if history_lineage is not None:
        face_lineage = history_lineage

    deleted_parent_faces = [
        face for face in parent_faces
        if str(face.get("face_fingerprint") or "") not in inherited_fingerprints
    ]
    operation_edges = [
        {"source": parent, "target": node["operation_id"], "relation": "declared_parent"}
        for node in operation_nodes for parent in node["parent_operation_ids"]
    ]
    inherited_count = sum(item["status"] == "inherited" for item in face_lineage)
    return {
        "schema_version": "1.0",
        "protocol": BOOLEAN_LINEAGE_PROTOCOL_ID,
        "snapshot_comparison": {
            "parent_face_count": len(parent_faces),
            "current_face_count": len(current_faces),
            "inherited_face_count": inherited_count,
            "created_or_modified_face_count": len(face_lineage) - inherited_count,
            "deleted_or_modified_parent_face_count": len(deleted_parent_faces),
            "captured_job_count": captured_job_count,
            "lineage_mode": (
                "multi_job_fingerprint_chain" if history_lineage is not None
                else "single_snapshot_delta"
            ),
        },
        "operation_graph": {"nodes": operation_nodes, "edges": operation_edges},
        "faces": face_lineage,
        "deleted_parent_face_examples": deleted_parent_faces[:32],
        "interpretation": (
            "Stable fingerprints prove inheritance. Snapshot-delta faces identify the operation "
            "group that changed topology; multiple operations in one job remain causally ambiguous."
        ),
    }


def _operation_candidates(
    face_matches: list[dict[str, Any]], features: list[dict[str, Any]], operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    handles = {str(item["entity_handle"]) for item in face_matches}
    fingerprints = {str(item.get("face_fingerprint")) for item in face_matches if item.get("face_fingerprint")}
    feature_ids = {str(item["feature_id"]) for item in features}
    lineage_evidence: dict[str, list[str]] = defaultdict(list)
    lineage_confidence: dict[str, list[str]] = defaultdict(list)
    for face in face_matches:
        lineage = face.get("boolean_lineage") or {}
        for operation_id in lineage.get("candidate_operation_ids", []):
            lineage_evidence[str(operation_id)].extend(lineage.get("evidence", []))
            lineage_confidence[str(operation_id)].append(str(lineage.get("confidence", "low")))
    results = []
    for operation in operations:
        operation_id = str(operation.get("operation_id"))
        evidence = []
        if not lineage_evidence and handles & {
            str(item) for item in operation.get("entity_handles", [])
        }:
            evidence.append("entity_handle")
        if fingerprints & {str(item) for item in operation.get("face_fingerprints", [])}:
            evidence.append("face_fingerprint")
        declared_feature_ids = {
            str(item) for item in operation.get("feature_ids", [])
        }
        if operation.get("feature_id"):
            declared_feature_ids.add(str(operation["feature_id"]))
        if feature_ids & declared_feature_ids:
            evidence.append("feature_id")
        if operation_id in lineage_evidence:
            evidence.extend(["boolean_face_lineage", *lineage_evidence[operation_id]])
        if evidence:
            evidence = list(dict.fromkeys(evidence))
            lineage_levels = lineage_confidence.get(operation_id, [])
            if "declared_face_fingerprint" in evidence or "face_fingerprint" in evidence:
                confidence = "high"
            elif "boolean_face_lineage" in evidence and lineage_levels == ["medium"]:
                confidence = "medium"
            elif evidence == ["entity_handle"] or "mcp_job_operation_group" in evidence:
                confidence = "low"
            else:
                confidence = "medium"
            results.append({
                "operation_id": operation.get("operation_id"),
                "intent": operation.get("intent"),
                "evidence": evidence,
                "confidence": confidence,
                "operation_type": operation.get("operation_type"),
                "feature_id": operation.get("feature_id"),
                "editable_parameters": deepcopy(operation.get("parameters") or {}),
                "parent_operation_ids": operation.get("parent_operation_ids", []),
            })
    return results


def enrich_localization_with_topology(
    localization: dict[str, Any], topology: dict[str, Any], *, candidate_bounds: list[list[float]],
    truth_bounds: list[list[float]], rotation: list[list[float]], operations: list[dict[str, Any]] | None = None,
    parent_topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach ranked candidate faces, inferred features, and declared operation provenance."""
    result = deepcopy(localization)
    candidate_center = [(candidate_bounds[0][i] + candidate_bounds[1][i]) / 2 for i in range(3)]
    truth_center = [(truth_bounds[0][i] + truth_bounds[1][i]) / 2 for i in range(3)]
    diagonal = math.sqrt(sum((truth_bounds[1][i] - truth_bounds[0][i]) ** 2 for i in range(3)))
    graph = build_feature_graph(topology)
    boolean_lineage = build_boolean_face_lineage(topology, parent_topology, operations)
    lineage_by_node = {item["node_id"]: item for item in boolean_lineage["faces"]}
    aligned_faces = []
    for node in graph["nodes"]:
        if not node.get("bounds"):
            continue
        aligned_faces.append((node, _aligned_bounds(node["bounds"], candidate_center, truth_center, rotation)))
    features_by_face: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for feature in graph["feature_candidates"]:
        for face_id in feature["face_ids"]:
            features_by_face[(feature["entity_handle"], face_id)].append(feature)

    for region in result.get("regions", []):
        ranking = []
        for node, aligned in aligned_faces:
            distance = _bbox_distance(region["bbox"], aligned)
            overlap = _bbox_overlap(region["bbox"], aligned)
            ranking.append((distance / max(diagonal, 1e-12), -overlap, node, aligned))
        ranking.sort(key=lambda item: (item[0], item[1], item[2]["node_id"]))
        best_distance = ranking[0][0] if ranking else math.inf
        selected = [item for item in ranking if item[0] <= best_distance + 0.005][:8]
        matches = [{
            "entity_handle": item[2]["entity_handle"],
            "face_id": item[2]["face_id"],
            "face_fingerprint": item[2].get("face_fingerprint"),
            "surface_type": item[2]["surface_type"],
            "area": item[2].get("area"),
            "aligned_bounds": item[3],
            "bbox_distance_normalized": round(item[0], 6),
            "bbox_overlap": round(-item[1], 6),
            "boolean_lineage": deepcopy(lineage_by_node.get(item[2]["node_id"])),
        } for item in selected]
        region["candidate_topology_faces"] = matches
        region["topology_mapping_confidence"] = (
            "high" if matches and matches[0]["bbox_overlap"] >= 0.25
            else "medium" if matches and matches[0]["bbox_distance_normalized"] <= 0.005
            else "low"
        )
        relevant_features = {}
        for match in matches:
            for feature in features_by_face[(match["entity_handle"], match["face_id"])]:
                relevant_features[feature["feature_id"]] = feature
        region["engineering_feature_candidates"] = list(relevant_features.values())
        region["responsible_operation_candidates"] = _operation_candidates(
            matches, list(relevant_features.values()), operations or [],
        )
    result["native_topology"] = {
        "protocol": FEATURE_PROTOCOL_ID,
        "entity_count": len(topology.get("entities", [])),
        "face_count": len(graph["nodes"]),
        "adjacency_count": len(graph["edges"]),
        "feature_candidate_count": len(graph["feature_candidates"]),
        "export_errors": topology.get("errors", []),
        "interpretation": "Face and operation links are ranked diagnostic evidence, not guaranteed feature-history recovery.",
        "boolean_lineage": {
            key: value for key, value in boolean_lineage.items() if key != "faces"
        },
    }
    return result


def face_query_rows(localization: dict[str, Any], alignment: dict[str, Any]) -> list[tuple[str, list[float]]]:
    """Transform region centroids and bounds from aligned truth space into candidate WCS."""
    candidate_center = alignment.get("candidate_center")
    truth_center = alignment.get("ground_truth_center")
    rotation = alignment.get("rotation")
    if not candidate_center or not truth_center or not rotation:
        return []
    rows = []
    for region in localization.get("regions", []):
        samples = region.get("source_surface_query_points") or [region["centroid"]]
        seen = set()
        for index, point in enumerate(samples):
            key = tuple(round(float(value), 9) for value in point)
            if key in seen:
                continue
            seen.add(key)
            relative = [float(point[axis]) - float(truth_center[axis]) for axis in range(3)]
            candidate_point = [
                sum(relative[row] * float(rotation[row][column]) for row in range(3))
                + float(candidate_center[column])
                for column in range(3)
            ]
            rows.append((f"{region['region_id']}#{index:02d}", candidate_point))
    return rows


def apply_exact_face_queries(
    localization: dict[str, Any], query: dict[str, Any], topology: dict[str, Any],
    *, operations: list[dict[str, Any]] | None = None, diagonal: float,
    parent_topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote AutoCAD trimmed-face distance results above bounding-box candidates."""
    result = deepcopy(localization)
    graph = build_feature_graph(topology)
    boolean_lineage = build_boolean_face_lineage(topology, parent_topology, operations)
    lineage_by_node = {item["node_id"]: item for item in boolean_lineage["faces"]}
    nodes = {(node["entity_handle"], node["face_id"]): node for node in graph["nodes"]}
    features_by_face: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for feature in graph["feature_candidates"]:
        for face_id in feature["face_ids"]:
            features_by_face[(feature["entity_handle"], face_id)].append(feature)
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in query.get("queries", []):
        by_region[str(item.get("query_id", "")).split("#", 1)[0]].append(item)

    for region in result.get("regions", []):
        queries = [item for item in by_region.get(region["region_id"], []) if item.get("face_id")]
        counts: dict[tuple[str, str], int] = defaultdict(int)
        distances: dict[tuple[str, str], list[float]] = defaultdict(list)
        methods: dict[tuple[str, str], set[str]] = defaultdict(set)
        for item in queries:
            key = (str(item["entity_handle"]), str(item["face_id"]))
            counts[key] += 1
            if item.get("distance") is not None:
                distances[key].append(float(item["distance"]))
            methods[key].add(str(item.get("method", "unknown")))
        ordered = sorted(counts, key=lambda key: (-counts[key], min(distances[key] or [math.inf]), key))
        existing = {
            (item["entity_handle"], item["face_id"]): item
            for item in region.get("candidate_topology_faces", [])
        }
        exact_matches = []
        for key in ordered[:8]:
            node = nodes.get(key, {})
            base = existing.get(key, {
                "entity_handle": key[0], "face_id": key[1],
                "face_fingerprint": node.get("face_fingerprint"),
                "surface_type": node.get("surface_type", "unknown"),
                "area": node.get("area"), "aligned_bounds": None,
                "bbox_distance_normalized": None, "bbox_overlap": None,
                "boolean_lineage": deepcopy(lineage_by_node.get(f"{key[0]}:{key[1]}")),
            })
            exact_matches.append({
                **base,
                "exact_query_hits": counts[key],
                "exact_query_fraction": round(counts[key] / max(len(queries), 1), 6),
                "minimum_trimmed_face_distance_normalized": round(
                    min(distances[key] or [math.inf]) / max(diagonal, 1e-12), 6,
                ),
                "query_methods": sorted(methods[key]),
            })
        if exact_matches:
            region["candidate_topology_faces"] = exact_matches
            top_fraction = exact_matches[0]["exact_query_fraction"]
            region["topology_mapping_confidence"] = (
                "high" if len(queries) >= 3 and top_fraction >= 0.6
                else "medium" if top_fraction >= 0.3 else "low"
            )
            relevant_features = {}
            for match in exact_matches:
                for feature in features_by_face[(match["entity_handle"], match["face_id"])]:
                    relevant_features[feature["feature_id"]] = feature
            region["engineering_feature_candidates"] = list(relevant_features.values())
            region["responsible_operation_candidates"] = _operation_candidates(
                exact_matches, list(relevant_features.values()), operations or [],
            )
        region["exact_face_query"] = {
            "query_count": len(queries),
            "mapped": bool(exact_matches),
            "method": "trimmed_brep_surface_and_boundary_distance",
        }
    result.setdefault("native_topology", {})["exact_face_query_count"] = len(query.get("queries", []))
    return result


def enrich_score_with_topology(
    score: dict[str, Any], topology: dict[str, Any], *,
    operations: list[dict[str, Any]] | None = None, query: dict[str, Any] | None = None,
    parent_topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich an already computed score without repeating mesh evaluation."""
    alignment = score["alignment"]
    candidate_center = alignment["candidate_center"]
    truth_center = alignment["ground_truth_center"]
    candidate_extents = score["candidate_geometry"]["extents"]
    truth_extents = score["ground_truth_geometry"]["extents"]
    candidate_bounds = [
        [candidate_center[i] - candidate_extents[i] / 2 for i in range(3)],
        [candidate_center[i] + candidate_extents[i] / 2 for i in range(3)],
    ]
    truth_bounds = [
        [truth_center[i] - truth_extents[i] / 2 for i in range(3)],
        [truth_center[i] + truth_extents[i] / 2 for i in range(3)],
    ]
    localization = enrich_localization_with_topology(
        score["mismatch"]["localization"], topology,
        candidate_bounds=candidate_bounds, truth_bounds=truth_bounds,
        rotation=alignment["rotation"], operations=operations,
        parent_topology=parent_topology,
    )
    if query is not None:
        diagonal = math.sqrt(sum(float(value) ** 2 for value in truth_extents))
        localization = apply_exact_face_queries(
            localization, query, topology, operations=operations, diagonal=diagonal,
            parent_topology=parent_topology,
        )
    score["mismatch"]["localization"] = localization
    return score


def load_topology(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != "1.0" or not isinstance(value.get("entities"), list):
        raise ValueError(f"Unsupported AutoCAD topology artifact: {path}")
    return value
