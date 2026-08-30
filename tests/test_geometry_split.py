from __future__ import annotations

import json

import pytest

from cad_evoloop.evaluation.geometry_split import (
    build_geometry_split,
    validate_geometry_split,
)


def _manifest(tmp_path):
    samples = []
    for dataset, count in (("ortho2cad", 40), ("omnimech", 10)):
        for index in range(count):
            samples.append({
                "sample_id": f"{dataset}:{index:03d}",
                "dataset": dataset,
                "ground_truth_step": f"{dataset}/{index:03d}.step",
                "input_images": [f"{dataset}/{index:03d}.png"],
            })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "samples": samples,
    }), encoding="utf-8")
    return manifest


def test_geometry_split_is_deterministic_stratified_and_disjoint(tmp_path) -> None:
    manifest = _manifest(tmp_path)

    first = build_geometry_split(manifest)
    second = build_geometry_split(manifest)

    assert first == second
    assert {name: len(ids) for name, ids in first["splits"].items()} == {
        "dev": 20,
        "validation": 10,
        "hidden_test": 20,
    }
    assert first["strata"]["ortho2cad"] == {
        "dev": 16,
        "validation": 8,
        "hidden_test": 16,
    }
    assert first["strata"]["omnimech"] == {
        "dev": 4,
        "validation": 2,
        "hidden_test": 4,
    }
    assert first["cost_pilot"]["strata"] == {"omnimech": 2, "ortho2cad": 8}
    assert set(first["cost_pilot"]["sample_ids"]).issubset(first["splits"]["dev"])


def test_geometry_split_validation_rejects_tampering(tmp_path) -> None:
    split = build_geometry_split(_manifest(tmp_path))
    split["splits"]["dev"].append(split["splits"]["validation"][0])

    with pytest.raises(ValueError, match="digest"):
        validate_geometry_split(split)
