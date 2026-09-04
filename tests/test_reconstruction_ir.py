from __future__ import annotations

from pathlib import Path

from cad_evoloop.agent.models.base import (
    ConversationHandle,
    ModelCapabilities,
    ModelRequest,
    ModelTurn,
)
from cad_evoloop.evaluation.reconstruction_ir import (
    IR_PROTOCOL,
    bind_reconstruction_ir,
    build_reconstruction_ir,
    oracle_packet_to_reconstruction_ir,
    summarize_reconstruction_ir,
    validate_reconstruction_ir,
)


def valid_ir(sample_id: str = "sample:1") -> dict:
    return {
        "schema_version": "1.0",
        "protocol": IR_PROTOCOL,
        "sample_id": sample_id,
        "source_kind": "image_inference",
        "source_summary": "One dimensioned orthographic view.",
        "units": "mm",
        "views": [{
            "view_id": "front", "projection": "front", "elements": [], "notes": "",
        }],
        "dimensions": [],
        "cross_view_correspondences": [],
        "features": [{
            "feature_id": "body",
            "feature_type": "free-form profile",
            "operation": "any_custom_geometry_operation",
            "intent": "main body",
            "geometry": {
                "representation": "profile",
                "description": "rectangle",
                "data_json": '{"profile":[[0,0],[10,0],[10,5],[0,5]]}',
            },
            "placement": {"description": "origin", "data_json": "{}"},
            "dimension_ids": [],
            "evidence_ids": ["front"],
            "dependencies": [],
            "confidence": 0.8,
            "alternatives": [],
        }],
        "constraints": [],
        "construction_hypotheses": [],
        "ambiguities": [],
        "global_confidence": 0.8,
    }


class FakeProvider:
    name = "fake-provider"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(images=True, structured_output=True, resumable_conversation=True)

    def start(self, request: ModelRequest):
        self.requests.append(request)
        return ConversationHandle(self.name, "thread-1"), ModelTurn(
            content='{"bad": true}', structured_output={"bad": True}, finish_reason="stop",
        )

    def continue_(self, handle: ConversationHandle, request: ModelRequest):
        self.requests.append(request)
        return handle, ModelTurn(
            content="valid", structured_output=valid_ir(), finish_reason="stop",
        )

    def cancel(self, handle: ConversationHandle) -> None:
        pass


def test_ir_validation_keeps_geometry_operations_open() -> None:
    value = bind_reconstruction_ir(valid_ir(), "sample:1")

    assert value["features"][0]["operation"] == "any_custom_geometry_operation"
    assert len(value["ir_sha256"]) == 64
    assert validate_reconstruction_ir(value, "sample:1") == []


def test_ir_diagnostics_count_evidence_status_without_restricting_operations() -> None:
    value = valid_ir()
    value["dimensions"] = [
        {
            "dimension_id": "d1", "quantity": "width", "value": 10, "unit": "mm",
            "applies_to": ["body"], "status": "observed", "evidence": "front",
            "confidence": 1.0,
        },
        {
            "dimension_id": "d2", "quantity": "depth", "value": 4, "unit": "mm",
            "applies_to": ["body"], "status": "inferred", "evidence": "projection",
            "confidence": 0.5,
        },
    ]
    value["features"][0]["dimension_ids"] = ["d1", "d2"]

    diagnostics = summarize_reconstruction_ir(value)

    assert diagnostics["dimension_status_counts"] == {
        "observed": 1, "inferred": 1, "assumed": 0, "unknown": 0,
    }
    assert diagnostics["operation_names"] == ["any_custom_geometry_operation"]
    assert diagnostics["feature_confidence"]["mean"] == 0.8


def test_ir_validation_checks_nested_open_json_and_boolean_references() -> None:
    value = valid_ir()
    value["features"][0]["alternatives"] = [{"description": "bad", "data_json": "{"}]
    value["construction_hypotheses"] = [{
        "hypothesis_id": "h1",
        "ordered_feature_ids": ["body"],
        "boolean_relations": [{
            "operation": "custom_join",
            "operand_feature_ids": ["body", "missing"],
            "result_feature_id": "body",
            "parameters_json": "not-json",
        }],
        "rationale": "test",
        "confidence": 0.5,
    }]

    errors = validate_reconstruction_ir(value, "sample:1")

    assert any("alternatives[0].data_json" in error for error in errors)
    assert any("unknown features: ['missing']" in error for error in errors)
    assert any("parameters_json must contain valid JSON" in error for error in errors)


def test_ir_builder_retries_invalid_structured_output_in_same_thread(tmp_path: Path) -> None:
    provider = FakeProvider()
    image = tmp_path / "input.png"
    image.write_bytes(b"image")

    result = build_reconstruction_ir(
        provider, sample_id="sample:1", images=[image], output_dir=tmp_path / "ir",
    )

    assert result.conversation_id == "thread-1"
    assert result.attempts == 2
    assert provider.requests[0].images == [image]
    assert provider.requests[1].images == []
    assert (tmp_path / "ir/rejected-ir-001.txt").is_file()
    assert (tmp_path / "ir/reconstruction-ir.json").is_file()
    assert (tmp_path / "ir/ir-validation.json").is_file()
    validation = (tmp_path / "ir/ir-validation.json").read_text(encoding="utf-8")
    assert '"dimension_status_counts"' in validation


def test_oracle_ir_preserves_unordered_inventory_without_boolean_plan() -> None:
    packet = {
        "sample_id": "sample:1",
        "oracle_level": "perception",
        "unordered_exact_features": [{
            "feature_token": "opaque-b",
            "operation": "extrude",
            "workplane_calls": [{"origin": [0, 0, 0]}],
            "sketch_calls": [{"method": "circle", "args": [2]}],
            "feature_calls": [{"method": "extrude", "args": [5]}],
            "parameters": {"distance": 5},
        }],
    }

    value = oracle_packet_to_reconstruction_ir(packet)

    assert value["source_kind"] == "gt_oracle"
    assert '"distance":5' in value["features"][0]["geometry"]["data_json"]
    assert value["features"][0]["dependencies"] == []
    assert value["construction_hypotheses"] == []


def test_plan_oracle_cannot_masquerade_as_oracle_ir() -> None:
    try:
        oracle_packet_to_reconstruction_ir({
            "sample_id": "sample:1", "oracle_level": "plan", "ordered_stages": [],
        })
    except ValueError as exc:
        assert "perception oracle" in str(exc)
    else:
        raise AssertionError("plan oracle should be rejected")
