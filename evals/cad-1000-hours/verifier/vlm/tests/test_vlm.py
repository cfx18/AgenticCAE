from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from verifier.vlm.evaluate import (
    aggregate_visual_results,
    evaluate_visual_gaps,
    merge_visual_result,
)
from verifier.vlm.provider import CodexCliProvider, validate_visual_result
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


def test_two_thirds_low_confidence_consensus_resolves() -> None:
    aggregate = aggregate_visual_results([
        visual_result(confidence=0.72),
        visual_result(confidence=0.78),
        visual_result(verdict="uncertain", confidence=0.4),
    ], ["R1"])

    merged = merge_visual_result(deterministic(), aggregate, ["R1"], 0.85)

    assert merged["decision"] == "pass"
    assert merged["resolved"][0]["accepted_by_consensus"] is True


def test_split_consensus_remains_incomplete() -> None:
    aggregate = aggregate_visual_results([
        visual_result(verdict="pass", confidence=0.9),
        visual_result(verdict="fail", confidence=0.9),
        visual_result(verdict="uncertain", confidence=0.4),
    ], ["R1"])

    merged = merge_visual_result(deterministic(), aggregate, ["R1"], 0.85)

    assert merged["decision"] == "incomplete"
    assert merged["unresolved"][0]["consensus"]["required_votes"] == 2


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


def test_scene_renderer_includes_native_circles(tmp_path: Path) -> None:
    scene = {"entities": [{
        "type": "AcDbCircle", "owner": "Model", "Visible": True,
        "Center": [0.0, 0.0, 0.0], "Radius": 20.0,
    }]}
    output = tmp_path / "circle.png"

    render_scene(scene, output, 300, 300)

    colors = Image.open(output).convert("RGB").getcolors(maxcolors=300 * 300)
    assert colors is not None and len(colors) > 1


def test_evaluate_visual_gaps_writes_auditable_result(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "task_desc.json").write_text('{"task":"draw"}', encoding="utf-8")
    (sample / "rubrics.json").write_text(json.dumps({
        "rubrics": [{"id": "R1", "requirement": "Visible profile"}],
    }), encoding="utf-8")
    deterministic = tmp_path / "deterministic.json"
    deterministic.write_text(json.dumps({
        "passed": True, "score": 100, "coverage": 75,
        "hard_gates": [{"id": "document", "status": "pass"}],
        "dimensions": [],
        "rubrics": [{"id": "R1", "status": "unverified"}],
    }), encoding="utf-8")
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), "white").save(candidate)
    Image.new("RGB", (32, 32), "white").save(reference)
    monkeypatch.setattr(
        "cad_evoloop.verification.vlm.evaluate.CodexCliProvider.evaluate",
        lambda self, prompt, images, schema_path, work_dir, expected_ids: (
            visual_result(), {"provider": "test", "model": self.model},
        ),
    )
    output = tmp_path / "visual.json"

    result = evaluate_visual_gaps(
        sample_dir=sample,
        deterministic_path=deterministic,
        candidate_images=[candidate],
        reference_images=[reference],
        output=output,
        work_dir=tmp_path / "work",
    )

    assert result["combined"]["decision"] == "pass"
    assert result["combined"]["coverage_after"] == 100.0
    assert json.loads(output.read_text(encoding="utf-8"))["target_rubric_ids"] == ["R1"]


def test_low_confidence_evaluation_expands_to_consensus(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "task_desc.json").write_text('{"task":"draw"}', encoding="utf-8")
    (sample / "rubrics.json").write_text(json.dumps({
        "rubrics": [{"id": "R1", "requirement": "Visible profile"}],
    }), encoding="utf-8")
    deterministic_path = tmp_path / "deterministic.json"
    deterministic_path.write_text(json.dumps(deterministic()), encoding="utf-8")
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), "white").save(candidate)
    Image.new("RGB", (32, 32), "white").save(reference)
    calls = []

    def fake_evaluate(self, prompt, images, schema_path, work_dir, expected_ids):
        calls.append(work_dir)
        return visual_result(confidence=0.75), {
            "provider": "test", "model": self.model, "usage": {"input_tokens": 10},
            "elapsed_seconds": 1,
        }

    monkeypatch.setattr(
        "cad_evoloop.verification.vlm.evaluate.CodexCliProvider.evaluate", fake_evaluate,
    )

    result = evaluate_visual_gaps(
        sample_dir=sample,
        deterministic_path=deterministic_path,
        candidate_images=[candidate],
        reference_images=[reference],
        output=tmp_path / "visual.json",
        work_dir=tmp_path / "work",
        max_evaluations=3,
    )

    assert len(calls) == 3
    assert result["combined"]["decision"] == "pass"
    assert result["provider"]["usage"]["input_tokens"] == 30


def test_production_consensus_does_not_short_circuit_high_confidence(
    tmp_path: Path, monkeypatch,
) -> None:
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "task_desc.json").write_text('{"task":"draw"}', encoding="utf-8")
    (sample / "rubrics.json").write_text(json.dumps({
        "rubrics": [{"id": "R1", "requirement": "Visible profile"}],
    }), encoding="utf-8")
    deterministic_path = tmp_path / "deterministic.json"
    deterministic_path.write_text(json.dumps(deterministic()), encoding="utf-8")
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), "white").save(candidate)
    Image.new("RGB", (32, 32), "white").save(reference)
    calls = []

    def fake_evaluate(self, prompt, images, schema_path, work_dir, expected_ids):
        calls.append(work_dir)
        return visual_result(confidence=0.99), {
            "provider": "test", "model": self.model, "usage": {}, "elapsed_seconds": 0,
        }

    monkeypatch.setattr(
        "cad_evoloop.verification.vlm.evaluate.CodexCliProvider.evaluate", fake_evaluate,
    )

    result = evaluate_visual_gaps(
        sample_dir=sample,
        deterministic_path=deterministic_path,
        candidate_images=[candidate],
        reference_images=[reference],
        output=tmp_path / "visual.json",
        work_dir=tmp_path / "work",
        max_evaluations=3,
    )

    assert len(calls) == 3
    assert result["consensus_policy"]["actual_evaluations"] == 3


def test_provider_retains_evaluator_usage_and_output_paths(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "image.png"
    schema = tmp_path / "schema.json"
    Image.new("RGB", (16, 16), "white").save(image)
    schema.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("cad_evoloop.verification.vlm.provider.shutil.which", lambda _: "codex")

    def fake_run(command, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text(json.dumps(visual_result()), encoding="utf-8")
        return __import__("subprocess").CompletedProcess(
            command, 0,
            stdout="\n".join([
                json.dumps({"type": "thread.started", "thread_id": "t1"}),
                json.dumps({"type": "turn.completed", "usage": {
                    "input_tokens": 10, "output_tokens": 2,
                }}),
            ]),
            stderr="",
        )

    monkeypatch.setattr("cad_evoloop.verification.vlm.provider.subprocess.run", fake_run)

    _, metadata = CodexCliProvider().evaluate(
        "evaluate", [image], schema, tmp_path / "work", ["R1"],
    )

    assert metadata["usage"] == {"input_tokens": 10, "output_tokens": 2}
    assert metadata["elapsed_seconds"] >= 0
    assert Path(metadata["result_path"]).is_file()
