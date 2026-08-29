from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from verifier.vlm.evaluate import merge_visual_result
from verifier.vlm.provider import validate_visual_result
from verifier.vlm.render_scene import render_scene


def visual_result(verdict: str = "pass", confidence: float = 0.9) -> dict:
    return {
        "image_quality": "sufficient",
        "rubrics": [{
            "id": "R1",
            "verdict": verdict,
            "confidence": confidence,
            "explanation": "The candidate visibly has the required arrangement.",
            "evidence": [{
                "image": "candidate.png",
                "description": "Visible profile",
                "region": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4},
            }],
        }],
        "global_notes": "",
    }


def deterministic(passed: bool = True) -> dict:
    return {
        "passed": passed,
        "coverage": 66.67,
        "hard_gates": [{"status": "pass"}],
        "dimensions": [{"status": "pass"}],
        "rubrics": [{"id": "R1", "status": "unverified"}],
    }


def test_visual_result_validation_is_strict() -> None:
    validate_visual_result(visual_result(), ["R1"])
    invalid = visual_result()
    invalid["rubrics"][0]["id"] = "R2"
    with pytest.raises(ValueError):
        validate_visual_result(invalid, ["R1"])


def test_evidence_region_must_stay_inside_image() -> None:
    invalid = visual_result()
    invalid["rubrics"][0]["evidence"][0]["region"] = {
        "x": 0.8, "y": 0.1, "width": 0.3, "height": 0.4,
    }
    with pytest.raises(ValueError, match="exceeds image bounds"):
        validate_visual_result(invalid, ["R1"])


def test_low_confidence_remains_incomplete() -> None:
    merged = merge_visual_result(deterministic(), visual_result(confidence=0.5), ["R1"], 0.85)
    assert merged["decision"] == "incomplete"
    assert merged["coverage_after"] == 66.67


def test_visual_pass_cannot_override_deterministic_failure() -> None:
    merged = merge_visual_result(deterministic(False), visual_result(), ["R1"], 0.85)
    assert merged["decision"] == "fail"


def test_scene_renderer_produces_nonblank_png(tmp_path: Path) -> None:
    scene = {
        "entities": [
            {
                "type": "AcDbPolyline",
                "owner": "Model",
                "Visible": True,
                "Coordinates": [0.0, 0.0, 100.0, 0.0, 100.0, 50.0, 0.0, 50.0],
                "Closed": True,
                "ConstantWidth": 5.0,
            },
            {
                "type": "AcDbText",
                "owner": "Model",
                "Visible": True,
                "InsertionPoint": [0.0, -10.0, 0.0],
                "TextString": "RECTANGLE",
            },
        ]
    }
    output = tmp_path / "scene.png"
    render_scene(scene, output, 400, 300)
    image = Image.open(output).convert("RGB")
    colors = image.getcolors(maxcolors=image.width * image.height)
    assert image.size == (400, 300)
    assert colors is not None and len(colors) > 1
