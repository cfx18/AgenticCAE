from __future__ import annotations

import hashlib
import json

import pytest

from cad_evoloop.evaluation import input_identifiability
from cad_evoloop.evaluation.input_identifiability import (
    build_identifiability_assessment,
    gt_feature_dimension_values,
    validate_probe_result,
)


def _dimension(text: str, value: float, places: int, quantity: str = "unknown") -> dict:
    return {
        "displayed_text": text,
        "numeric_value": value,
        "decimal_places": places,
        "quantity": quantity,
        "view": "front",
        "evidence_region": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05},
    }


def _record(dimensions: list[dict], complete: bool = False) -> dict:
    return {
        "result": {
            "explicit_dimensions": dimensions,
            "dimensionally_complete": complete,
        },
    }


def test_gt_feature_values_include_sketch_origins_and_both_side_extent() -> None:
    trajectory = {
        "feature_dag": {
            "nodes": [{
                "kind": "feature",
                "parameters": {"distance": 0.125, "both": True},
                "sketch": {"calls": [{"args": [0.75, 0.2]}]},
                "workplane": {"calls": [{
                    "args": [{"expression": "cq.Plane(cq.Vector(0, -0.3, 0.4), cq.Vector(0, 1, 0))"}],
                }]},
            }],
        },
    }

    assert gt_feature_dimension_values(trajectory) == [0.125, 0.2, 0.25, 0.3, 0.4, 0.75]


def test_assessment_matches_only_explicit_dimensions_at_display_precision() -> None:
    trajectory = {
        "sample_id": "ortho2cad:test",
        "feature_dag": {
            "nodes": [{
                "kind": "feature",
                "parameters": {"distance": 0.1328125, "both": True},
                "sketch": {"calls": [{"args": [0.75, 0.742105]}]},
                "workplane": {"calls": []},
            }],
        },
    }
    dimensions = [
        _dimension("0.7500", 0.75, 4, "overall_length"),
        _dimension("0.7421", 0.7421, 4, "overall_height"),
        _dimension("0.2656", 0.2656, 4, "overall_width"),
    ]

    result = build_identifiability_assessment(
        trajectory,
        [_record(dimensions), _record(dimensions), _record(dimensions)],
        {"score": 100.0},
    )

    assert result["gt_values_matched_by_explicit_dimensions"] == [0.265625, 0.742105, 0.75]
    assert result["gt_values_without_explicit_dimension_match"] == [0.1328125]
    assert result["explicit_parameter_coverage"] == 0.75
    assert result["dimensionally_complete_for_exact_reconstruction"] is False


def test_probe_validation_rejects_duplicate_or_out_of_bounds_evidence() -> None:
    dimension = _dimension("1.00", 1.0, 2)
    value = {
        "schema_version": "1.0",
        "sample_id": "sample",
        "image_quality": "sufficient",
        "explicit_dimensions": [dimension, dict(dimension)],
        "dimensionally_complete": False,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        validate_probe_result(value, "sample")

    value["explicit_dimensions"] = [dimension]
    dimension["evidence_region"]["x"] = 0.95
    dimension["evidence_region"]["width"] = 0.1
    with pytest.raises(ValueError, match="exceeds"):
        validate_probe_result(value, "sample")


def test_cached_probe_is_hash_bound_to_model_prompt_and_input(tmp_path) -> None:
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    run_dir = tmp_path / "replicates" / "r001"
    run_dir.mkdir(parents=True)
    result = {
        "schema_version": "1.0", "sample_id": "sample",
        "image_quality": "sufficient", "explicit_dimensions": [],
        "dimensionally_complete": False,
    }
    record = {
        "schema_version": "1.0",
        "protocol": input_identifiability.IDENTIFIABILITY_PROTOCOL,
        "replicate": 1,
        "sample_id": "sample",
        "model": "sol",
        "reasoning_effort": "medium",
        "input_sha256": [input_identifiability.sha256_file(image)],
        "prompt_sha256": hashlib.sha256(
            input_identifiability._probe_prompt("sample").encode("utf-8")
        ).hexdigest(),
        "result": result,
    }
    record["record_sha256"] = input_identifiability._canonical_hash(record, "record_sha256")
    (run_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")

    cached = input_identifiability._run_probe_once(
        sample_id="sample", images=[image], output_dir=tmp_path,
        model="sol", effort="medium", executable="missing",
        timeout=1, replicate=1,
    )
    assert cached["record_sha256"] == record["record_sha256"]

    with pytest.raises(ValueError, match="immutable controls"):
        input_identifiability._run_probe_once(
            sample_id="sample", images=[image], output_dir=tmp_path,
            model="other", effort="medium", executable="missing",
            timeout=1, replicate=1,
        )
