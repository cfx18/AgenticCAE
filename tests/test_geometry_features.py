from __future__ import annotations

from cad_evoloop.evaluation.geometry_features import (
    apply_exact_face_queries,
    build_boolean_face_lineage,
    build_feature_graph,
    enrich_localization_with_topology,
    face_query_rows,
)


def sample_topology() -> dict:
    return {
        "schema_version": "1.0",
        "entities": [{
            "handle": "2A",
            "faces": [
                {"id": "f1", "fingerprint": "fp-plane", "area": 10, "bounds": {"min": [0, 0, 0], "max": [10, 10, 0]}, "surface": {"type": "plane"}, "edge_ids": ["e1"]},
                {"id": "f2", "fingerprint": "fp-hole", "area": 5, "bounds": {"min": [4, 4, 0], "max": [6, 6, 10]}, "surface": {"type": "cylinder", "radius": 1, "outer_normal": True}, "orientation_to_surface": False, "edge_ids": ["e1"]},
            ],
            "edges": [{"id": "e1", "face_ids": ["f1", "f2"]}],
        }],
        "errors": [],
    }


def test_feature_graph_keeps_face_adjacency_and_conservative_hole_candidate() -> None:
    graph = build_feature_graph(sample_topology())
    assert graph["edges"] == [{"source": "2A:f1", "target": "2A:f2", "relation": "shares_brep_edge"}]
    assert graph["feature_candidates"][0]["kind"] == "hole_candidate"
    assert graph["feature_candidates"][0]["parameters"]["radius"] == 1


def test_boolean_lineage_distinguishes_inherited_and_operation_created_faces() -> None:
    parent = sample_topology()
    parent["entities"][0]["faces"] = parent["entities"][0]["faces"][:1]
    lineage = build_boolean_face_lineage(
        sample_topology(), parent,
        [{
            "operation_id": "op-hole", "intent": "subtract through hole",
            "operation_type": "subtract", "feature_id": "mount-hole",
            "parameters": {"diameter": 2}, "target_entity_handles": ["2A"],
        }],
    )

    by_face = {item["face_id"]: item for item in lineage["faces"]}
    assert by_face["f1"]["status"] == "inherited"
    assert by_face["f1"]["candidate_operation_ids"] == []
    assert by_face["f2"]["status"] == "created_or_modified"
    assert by_face["f2"]["candidate_operation_ids"] == ["op-hole"]
    assert by_face["f2"]["confidence"] == "medium"
    assert lineage["snapshot_comparison"]["inherited_face_count"] == 1
    assert lineage["operation_graph"]["nodes"][0]["parameters"] == {"diameter": 2}


def test_boolean_lineage_marks_multi_operation_job_as_ambiguous() -> None:
    lineage = build_boolean_face_lineage(
        sample_topology(), {"entities": []},
        [
            {"operation_id": "op-base", "intent": "base"},
            {"operation_id": "op-hole", "intent": "hole", "parent_operation_ids": ["op-base"]},
        ],
    )
    assert lineage["faces"][0]["confidence"] == "low"
    assert lineage["faces"][0]["candidate_operation_ids"] == ["op-base", "op-hole"]
    assert lineage["operation_graph"]["edges"] == [{
        "source": "op-base", "target": "op-hole", "relation": "declared_parent",
    }]


def test_localization_maps_region_to_face_feature_and_declared_operation() -> None:
    localization = {"regions": [{"region_id": "excess-01", "bbox": {"min": [4.5, 4.5, 2], "max": [5.5, 5.5, 8]}}]}
    result = enrich_localization_with_topology(
        localization,
        sample_topology(),
        candidate_bounds=[[0, 0, 0], [10, 10, 10]],
        truth_bounds=[[0, 0, 0], [10, 10, 10]],
        rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        operations=[{"operation_id": "op-hole", "intent": "subtract hole", "face_fingerprints": ["fp-hole"]}],
    )
    region = result["regions"][0]
    assert region["candidate_topology_faces"][0]["face_id"] == "f2"
    assert region["engineering_feature_candidates"][0]["kind"] == "hole_candidate"
    assert region["responsible_operation_candidates"][0]["operation_id"] == "op-hole"
    assert localization["regions"][0].get("candidate_topology_faces") is None


def test_face_query_rows_invert_alignment_and_exact_hits_replace_bbox_ranking() -> None:
    localization = {"regions": [{
        "region_id": "missing-01", "centroid": [11, 22, 33],
        "bbox": {"min": [11, 22, 33], "max": [11, 22, 33]},
    }]}
    rows = face_query_rows(localization, {
        "candidate_center": [1, 2, 3], "ground_truth_center": [10, 20, 30],
        "rotation": [[1, 0, 0], [0, 0, -1], [0, 1, 0]],
    })
    assert rows == [("missing-01#00", [2.0, 5.0, 1.0])]

    enriched = enrich_localization_with_topology(
        localization, sample_topology(), candidate_bounds=[[0, 0, 0], [10, 10, 10]],
        truth_bounds=[[0, 0, 0], [10, 10, 10]],
        rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    )
    exact = apply_exact_face_queries(
        enriched,
        {"queries": [{
            "query_id": "missing-01#00", "entity_handle": "2A", "face_id": "f2",
            "distance": 0.1, "method": "trimmed_surface",
        }]},
        sample_topology(), diagonal=17.32,
    )
    region = exact["regions"][0]
    assert region["candidate_topology_faces"][0]["face_id"] == "f2"
    assert region["candidate_topology_faces"][0]["exact_query_hits"] == 1
    assert region["exact_face_query"]["mapped"] is True
