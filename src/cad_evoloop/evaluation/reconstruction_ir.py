"""Structured image-to-CAD intermediate representation and builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from cad_evoloop.agent.models.base import ModelProvider, ModelRequest
from cad_evoloop.paths import project_root


IR_PROTOCOL = "evocad-reconstruction-ir-v1"
IR_MODES = ("baseline", "forced_ir", "specialist_ir", "oracle_ir")
IR_BUILDER_MAX_ATTEMPTS = 3


def reconstruction_ir_schema() -> dict[str, Any]:
    path = project_root() / "src/cad_evoloop/evaluation/schemas/reconstruction-ir.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(value: dict[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_confidence(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value <= 1


def _valid_json_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return False
    return True


def summarize_reconstruction_ir(value: dict[str, Any]) -> dict[str, Any]:
    """Return compact, deterministic diagnostics for review and ablation reports."""
    dimensions = value.get("dimensions", [])
    features = value.get("features", [])
    confidence_values = [
        float(row["confidence"])
        for row in features
        if isinstance(row, dict) and _is_confidence(row.get("confidence"))
    ]
    status_counts = {
        status: sum(
            1 for row in dimensions
            if isinstance(row, dict) and row.get("status") == status
        )
        for status in ("observed", "inferred", "assumed", "unknown")
    }
    return {
        "view_count": len(value.get("views", [])),
        "dimension_count": len(dimensions),
        "dimension_status_counts": status_counts,
        "cross_view_correspondence_count": len(
            value.get("cross_view_correspondences", [])
        ),
        "feature_count": len(features),
        "feature_confidence": {
            "minimum": min(confidence_values) if confidence_values else None,
            "mean": (
                round(sum(confidence_values) / len(confidence_values), 6)
                if confidence_values else None
            ),
            "maximum": max(confidence_values) if confidence_values else None,
        },
        "operation_names": sorted({
            str(row["operation"])
            for row in features
            if isinstance(row, dict) and row.get("operation")
        }),
        "constraint_count": len(value.get("constraints", [])),
        "construction_hypothesis_count": len(
            value.get("construction_hypotheses", [])
        ),
        "ambiguity_count": len(value.get("ambiguities", [])),
        "global_confidence": value.get("global_confidence"),
    }


def validate_reconstruction_ir(value: dict[str, Any], sample_id: str) -> list[str]:
    """Return semantic errors not expressible reliably through provider schemas."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["IR must be a JSON object"]
    if value.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if value.get("protocol") != IR_PROTOCOL:
        errors.append(f"protocol must be {IR_PROTOCOL}")
    if value.get("sample_id") != sample_id:
        errors.append("sample_id does not match the requested sample")
    if value.get("source_kind") not in {"image_inference", "gt_oracle"}:
        errors.append("source_kind must be image_inference or gt_oracle")
    if not isinstance(value.get("source_summary"), str):
        errors.append("source_summary must be a string")
    if not isinstance(value.get("units"), str) or not value.get("units", "").strip():
        errors.append("units must be a non-empty string")

    views = value.get("views")
    if not isinstance(views, list) or not views:
        errors.append("at least one view is required")
        views = []
    features = value.get("features")
    if not isinstance(features, list) or not features:
        errors.append("at least one feature hypothesis is required")
        features = []

    identifiers: dict[str, str] = {}
    element_ids: set[str] = set()
    collections = (
        ("views", views, "view_id"),
        ("dimensions", value.get("dimensions", []), "dimension_id"),
        ("cross_view_correspondences", value.get("cross_view_correspondences", []), "correspondence_id"),
        ("features", features, "feature_id"),
        ("constraints", value.get("constraints", []), "constraint_id"),
        ("ambiguities", value.get("ambiguities", []), "ambiguity_id"),
    )
    for required_collection in (
        "dimensions", "cross_view_correspondences", "constraints",
        "construction_hypotheses", "ambiguities",
    ):
        if not isinstance(value.get(required_collection), list):
            errors.append(f"{required_collection} must be an array")
    for collection_name, rows, key in collections:
        if not isinstance(rows, list):
            errors.append(f"{collection_name} must be an array")
            continue
        for index, row in enumerate(rows):
            identifier = row.get(key) if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"{collection_name}[{index}].{key} must be non-empty")
            elif identifier in identifiers:
                errors.append(
                    f"identifier {identifier!r} is reused by {collection_name} and {identifiers[identifier]}"
                )
            else:
                identifiers[identifier] = collection_name

    for view_index, view in enumerate(views):
        if not isinstance(view, dict):
            errors.append(f"views[{view_index}] must be an object")
            continue
        elements = view.get("elements")
        if not isinstance(elements, list):
            errors.append(f"views[{view_index}].elements must be an array")
            continue
        for element_index, element in enumerate(elements):
            identifier = element.get("element_id") if isinstance(element, dict) else None
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(
                    f"views[{view_index}].elements[{element_index}].element_id must be non-empty"
                )
            elif identifier in element_ids or identifier in identifiers:
                errors.append(f"element identifier {identifier!r} is not globally unique")
            else:
                element_ids.add(identifier)
            if isinstance(element, dict):
                geometry = element.get("geometry")
                if not isinstance(geometry, dict) or not _valid_json_text(
                    geometry.get("data_json")
                ):
                    errors.append(
                        f"views[{view_index}].elements[{element_index}].geometry.data_json "
                        "must contain valid JSON"
                    )

    feature_ids = {
        row.get("feature_id") for row in features
        if isinstance(row, dict) and isinstance(row.get("feature_id"), str)
    }
    dimension_ids = {
        row.get("dimension_id") for row in value.get("dimensions", [])
        if isinstance(row, dict) and isinstance(row.get("dimension_id"), str)
    }
    evidence_ids = element_ids | {
        row.get("view_id") for row in views
        if isinstance(row, dict) and isinstance(row.get("view_id"), str)
    }

    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            errors.append(f"features[{index}] must be an object")
            continue
        if not isinstance(feature.get("operation"), str) or not feature.get("operation", "").strip():
            errors.append(f"features[{index}].operation must be non-empty")
        if not isinstance(feature.get("geometry"), dict):
            errors.append(f"features[{index}].geometry must be an object")
        elif not _valid_json_text(feature["geometry"].get("data_json")):
            errors.append(f"features[{index}].geometry.data_json must contain valid JSON")
        if not isinstance(feature.get("placement"), dict):
            errors.append(f"features[{index}].placement must be an object")
        elif not _valid_json_text(feature["placement"].get("data_json")):
            errors.append(f"features[{index}].placement.data_json must contain valid JSON")
        if not _is_confidence(feature.get("confidence")):
            errors.append(f"features[{index}].confidence must be between 0 and 1")
        unknown_dimensions = set(feature.get("dimension_ids") or []) - dimension_ids
        if unknown_dimensions:
            errors.append(
                f"features[{index}] references unknown dimensions: {sorted(unknown_dimensions)}"
            )
        unknown_evidence = set(feature.get("evidence_ids") or []) - evidence_ids
        if unknown_evidence:
            errors.append(
                f"features[{index}] references unknown evidence: {sorted(unknown_evidence)}"
            )
        unknown_dependencies = set(feature.get("dependencies") or []) - feature_ids
        if unknown_dependencies:
            errors.append(
                f"features[{index}] references unknown dependencies: {sorted(unknown_dependencies)}"
            )
        for alternative_index, alternative in enumerate(feature.get("alternatives") or []):
            if not isinstance(alternative, dict) or not _valid_json_text(
                alternative.get("data_json")
            ):
                errors.append(
                    f"features[{index}].alternatives[{alternative_index}].data_json "
                    "must contain valid JSON"
                )

    for index, row in enumerate(value.get("cross_view_correspondences", [])):
        if not isinstance(row, dict):
            continue
        unknown = set(row.get("element_ids") or []) - element_ids
        if unknown:
            errors.append(
                f"cross_view_correspondences[{index}] references unknown elements: {sorted(unknown)}"
            )

    graph = {
        feature.get("feature_id"): list(feature.get("dependencies") or [])
        for feature in features if isinstance(feature, dict) and feature.get("feature_id")
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(parent) for parent in graph.get(node, []) if parent in graph):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in graph if node not in visited):
        errors.append("feature dependencies must be acyclic")

    for index, hypothesis in enumerate(value.get("construction_hypotheses", [])):
        if not isinstance(hypothesis, dict):
            errors.append(f"construction_hypotheses[{index}] must be an object")
            continue
        unknown = set(hypothesis.get("ordered_feature_ids") or []) - feature_ids
        if unknown:
            errors.append(
                f"construction_hypotheses[{index}] references unknown features: {sorted(unknown)}"
            )
        for relation_index, relation in enumerate(hypothesis.get("boolean_relations") or []):
            if not isinstance(relation, dict):
                errors.append(
                    f"construction_hypotheses[{index}].boolean_relations[{relation_index}] "
                    "must be an object"
                )
                continue
            relation_refs = set(relation.get("operand_feature_ids") or [])
            result_ref = relation.get("result_feature_id")
            if isinstance(result_ref, str):
                relation_refs.add(result_ref)
            unknown_relation_refs = relation_refs - feature_ids
            if unknown_relation_refs:
                errors.append(
                    f"construction_hypotheses[{index}].boolean_relations[{relation_index}] "
                    f"references unknown features: {sorted(unknown_relation_refs)}"
                )
            if not _valid_json_text(relation.get("parameters_json")):
                errors.append(
                    f"construction_hypotheses[{index}].boolean_relations[{relation_index}]"
                    ".parameters_json must contain valid JSON"
                )

    for index, constraint in enumerate(value.get("constraints", [])):
        if isinstance(constraint, dict) and not _valid_json_text(
            constraint.get("parameters_json")
        ):
            errors.append(f"constraints[{index}].parameters_json must contain valid JSON")

    for index, ambiguity in enumerate(value.get("ambiguities", [])):
        if not isinstance(ambiguity, dict):
            continue
        for candidate_index, candidate in enumerate(ambiguity.get("candidates") or []):
            if not isinstance(candidate, dict) or not _valid_json_text(
                candidate.get("data_json")
            ):
                errors.append(
                    f"ambiguities[{index}].candidates[{candidate_index}].data_json "
                    "must contain valid JSON"
                )

    if not _is_confidence(value.get("global_confidence")):
        errors.append("global_confidence must be between 0 and 1")
    return errors


def bind_reconstruction_ir(value: dict[str, Any], sample_id: str) -> dict[str, Any]:
    errors = validate_reconstruction_ir(value, sample_id)
    if errors:
        raise ValueError("Invalid reconstruction IR: " + "; ".join(errors))
    bound = dict(value)
    bound["ir_sha256"] = _canonical_hash(bound, "ir_sha256")
    return bound


def oracle_packet_to_reconstruction_ir(packet: dict[str, Any]) -> dict[str, Any]:
    """Translate an unordered exact-feature oracle without inventing an operation order."""
    if packet.get("oracle_level") != "perception":
        raise ValueError("oracle_ir requires an unordered perception oracle packet")
    features = []
    for index, row in enumerate(packet.get("unordered_exact_features", []), 1):
        operation = str(row.get("operation") or "exact_feature")
        features.append({
            "feature_id": str(row.get("feature_token") or f"oracle-feature-{index:03d}"),
            "feature_type": operation,
            "operation": operation,
            "intent": "Exact GT-derived feature inventory; construction order is withheld.",
            "geometry": {
                "representation": "exact_feature_calls",
                "description": "Exact workplane, sketch, and feature calls from the oracle.",
                "data_json": json.dumps({
                    "workplane_calls": row.get("workplane_calls", []),
                    "sketch_calls": row.get("sketch_calls", []),
                    "feature_calls": row.get("feature_calls", []),
                    "parameters": row.get("parameters", {}),
                }, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            },
            "placement": {
                "description": "Placement is encoded in the exact workplane calls.",
                "data_json": "{}",
            },
            "dimension_ids": [],
            "evidence_ids": ["oracle-parameter-space"],
            "dependencies": [],
            "confidence": 1.0,
            "alternatives": [],
        })
    value = {
        "schema_version": "1.0",
        "protocol": IR_PROTOCOL,
        "sample_id": packet.get("sample_id"),
        "source_kind": "gt_oracle",
        "source_summary": (
            "Unordered exact feature inventory derived from evaluator GT. Feature order and "
            "Boolean plan are intentionally withheld."
        ),
        "units": "dataset_native",
        "views": [{
            "view_id": "oracle-parameter-space",
            "projection": "parameter_space",
            "elements": [],
            "notes": "This intervention replaces image inference with exact feature parameters.",
        }],
        "dimensions": [],
        "cross_view_correspondences": [],
        "features": features,
        "constraints": [],
        "construction_hypotheses": [],
        "ambiguities": [],
        "global_confidence": 1.0,
    }
    return bind_reconstruction_ir(value, str(packet.get("sample_id")))


def _builder_prompt(sample_id: str) -> str:
    return f"""You are EvoCAD's image-to-CAD IR Builder for sample {sample_id}.

Analyze every attached engineering drawing view before proposing construction. Do not create CAD,
call tools, or produce executable geometry code. Externalize the complete reconstruction state as
JSON matching the supplied schema. Record observed dimensions separately from inferred or assumed
dimensions. Establish cross-view correspondences, feature hypotheses, constraints, a tentative
construction hypothesis, ambiguities, alternatives, and calibrated confidence.

The IR is an evidence model, not a restricted CAD command language. The `operation` field may name
any geometry operation needed by the drawing. Preserve arbitrary geometric data inside `data_json`
as valid JSON text; this transport encoding must not force the part into a known feature vocabulary.

Use `source_kind` = `image_inference`, `protocol` = `{IR_PROTOCOL}`, `schema_version` = `1.0`, and
`sample_id` = `{sample_id}`. Never claim an unshown dimension was observed. When the drawing is
insufficient for exact reconstruction, preserve competing hypotheses in `ambiguities` rather than
silently choosing one."""


@dataclass(frozen=True)
class IRBuildResult:
    value: dict[str, Any]
    conversation_id: str
    attempts: int
    paths: tuple[Path, ...]


def build_reconstruction_ir(
    provider: ModelProvider,
    *,
    sample_id: str,
    images: list[Path],
    output_dir: Path,
    max_attempts: int = IR_BUILDER_MAX_ATTEMPTS,
) -> IRBuildResult:
    if max_attempts < 1:
        raise ValueError("IR builder max_attempts must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    schema = reconstruction_ir_schema()
    traces: list[dict[str, Any]] = []
    request = ModelRequest(
        instructions=_builder_prompt(sample_id),
        images=images,
        response_schema=schema,
        metadata={"sample_id": sample_id, "stage": "reconstruction_ir"},
    )
    handle = None
    accepted = None
    for attempt in range(1, max_attempts + 1):
        if handle is None:
            handle, turn = provider.start(request)
        else:
            handle, turn = provider.continue_(handle, request)
        candidate = turn.structured_output
        errors = (
            validate_reconstruction_ir(candidate, sample_id)
            if isinstance(candidate, dict) else ["model response was not a JSON object"]
        )
        trace = {
            "attempt": attempt,
            "finish_reason": turn.finish_reason,
            "usage": turn.usage,
            "validation_errors": errors,
            "provider_metadata": turn.provider_metadata,
        }
        traces.append(trace)
        if not errors and isinstance(candidate, dict):
            accepted = bind_reconstruction_ir(candidate, sample_id)
            break
        rejected = output_dir / f"rejected-ir-{attempt:03d}.txt"
        rejected.write_text(turn.content or "", encoding="utf-8", newline="\n")
        request = ModelRequest(
            instructions=(
                "Your previous reconstruction IR failed validation. Return a complete replacement "
                "JSON object matching the schema. Fix every listed error without deleting valid "
                "drawing evidence.\n\nValidation errors:\n- " + "\n- ".join(errors)
            ),
            response_schema=schema,
            metadata={"sample_id": sample_id, "stage": "reconstruction_ir_correction"},
        )
    if accepted is None or handle is None:
        record_path = output_dir / "ir-build-record.json"
        record_path.write_text(
            json.dumps({
                "schema_version": "1.0", "protocol": IR_PROTOCOL,
                "sample_id": sample_id, "status": "failed", "attempts": traces,
            }, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            f"IR Builder did not produce valid structured output after {max_attempts} attempts"
        )

    ir_path = output_dir / "reconstruction-ir.json"
    ir_path.write_text(json.dumps(accepted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    validation = {
        "schema_version": "1.0", "protocol": IR_PROTOCOL,
        "sample_id": sample_id, "status": "passed", "errors": [],
        "ir_sha256": accepted["ir_sha256"],
        "diagnostics": summarize_reconstruction_ir(accepted),
    }
    validation_path = output_dir / "ir-validation.json"
    validation_path.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    record = {
        "schema_version": "1.0", "protocol": IR_PROTOCOL,
        "sample_id": sample_id, "status": "passed", "provider": provider.name,
        "conversation_id": handle.conversation_id, "attempt_count": len(traces),
        "ir_sha256": accepted["ir_sha256"], "attempts": traces,
    }
    record_path = output_dir / "ir-build-record.json"
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    paths = [ir_path, validation_path, record_path]
    paths.extend(sorted(output_dir.glob("rejected-ir-*.txt")))
    return IRBuildResult(
        value=accepted,
        conversation_id=handle.conversation_id,
        attempts=len(traces),
        paths=tuple(paths),
    )
