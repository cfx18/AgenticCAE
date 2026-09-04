"""Evaluator-side probes for whether an input drawing specifies its GT geometry."""

from __future__ import annotations

from collections import Counter
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from cad_evoloop.agent.models.codex_cli import parse_codex_events
from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root

from .geometry_campaign import load_geometry_manifest
from .gt_trajectory import (
    _canonical_hash,
    _workspace_path,
    extract_gt_feature_trajectory,
    verify_ground_truth_self_consistency,
)


IDENTIFIABILITY_PROTOCOL = "evocad-input-identifiability-v1"
PROHIBITED_EVENT_ITEMS = {
    "command_execution", "computer_tool_call", "file_search_call",
    "mcp_tool_call", "web_search_call",
}


def _probe_prompt(sample_id: str) -> str:
    return f"""You are an evaluator-side CAD drawing observability probe for sample {sample_id}.

Inspect only the attached input drawing. Do not use tools, files, shell commands, web
search, CAD software, or outside knowledge. Extract every numeric dimension that is
explicitly printed in the drawing. Do not estimate dimensions from pixels and do not
turn unlabeled proportions into numeric values.

For each printed dimension, preserve displayed_text exactly, parse numeric_value,
count decimal_places, classify its quantity and view, and give a normalized image
evidence_region containing the printed text. List visible but unlabeled geometric
features separately. dimensionally_complete is true only if all feature sizes,
locations, profiles, radii, and angles needed for exact reconstruction are explicitly
dimensioned. Return only the required JSON object."""


def validate_probe_result(value: dict[str, Any], sample_id: str) -> None:
    if value.get("schema_version") != "1.0" or value.get("sample_id") != sample_id:
        raise ValueError("Identifiability probe is bound to a different sample")
    if value.get("image_quality") not in {"sufficient", "insufficient"}:
        raise ValueError("Invalid identifiability image_quality")
    dimensions = value.get("explicit_dimensions")
    if not isinstance(dimensions, list):
        raise ValueError("explicit_dimensions must be an array")
    seen = set()
    for dimension in dimensions:
        key = (dimension.get("displayed_text"), dimension.get("view"))
        if key in seen:
            raise ValueError(f"Duplicate explicit dimension: {key}")
        seen.add(key)
        number = dimension.get("numeric_value")
        places = dimension.get("decimal_places")
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            raise ValueError("Dimension numeric_value must be numeric")
        if not isinstance(places, int) or not 0 <= places <= 12:
            raise ValueError("Dimension decimal_places is invalid")
        region = dimension.get("evidence_region")
        if not isinstance(region, dict) or set(region) != {"x", "y", "width", "height"}:
            raise ValueError("Dimension evidence_region is invalid")
        if any(not isinstance(region[key], (int, float)) or not 0 <= region[key] <= 1 for key in region):
            raise ValueError("Dimension evidence_region is out of range")
        if region["x"] + region["width"] > 1 or region["y"] + region["height"] > 1:
            raise ValueError("Dimension evidence_region exceeds image bounds")
    if not isinstance(value.get("dimensionally_complete"), bool):
        raise ValueError("dimensionally_complete must be Boolean")


def _run_probe_once(
    *,
    sample_id: str,
    images: list[Path],
    output_dir: Path,
    model: str,
    effort: str,
    executable: str,
    timeout: int,
    replicate: int,
) -> dict[str, Any]:
    run_dir = output_dir / "replicates" / f"r{replicate:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    record_path = run_dir / "record.json"
    if record_path.is_file():
        cached = json.loads(record_path.read_text(encoding="utf-8"))
        if cached.get("record_sha256") != _canonical_hash(cached, "record_sha256"):
            raise ValueError(f"Cached probe record digest mismatch: {record_path}")
        expected_inputs = [sha256_file(image) for image in images]
        expected_prompt = hashlib.sha256(_probe_prompt(sample_id).encode("utf-8")).hexdigest()
        if any([
            cached.get("sample_id") != sample_id,
            cached.get("model") != model,
            cached.get("reasoning_effort") != effort,
            cached.get("input_sha256") != expected_inputs,
            cached.get("prompt_sha256") != expected_prompt,
        ]):
            raise ValueError(f"Cached probe record uses different immutable controls: {record_path}")
        validate_probe_result(cached["result"], sample_id)
        return cached
    existing = [path for path in run_dir.iterdir()]
    if existing:
        archive_root = output_dir / "failed-invocations" / f"r{replicate:03d}"
        archive_number = max(
            [int(path.name[1:]) for path in archive_root.glob("f[0-9][0-9][0-9]")],
            default=0,
        ) + 1 if archive_root.is_dir() else 1
        archive = archive_root / f"f{archive_number:03d}"
        archive.mkdir(parents=True)
        for path in existing:
            shutil.move(str(path), archive / path.name)
    schema = project_root() / "src/cad_evoloop/evaluation/schemas/input-identifiability.schema.json"
    prompt = _probe_prompt(sample_id)
    prompt_path = run_dir / "prompt.txt"
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    result_path = run_dir / "model-result.json"
    prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
    command = [
        executable, "exec", "--ephemeral", "--skip-git-repo-check",
        "--ignore-rules", "--ignore-user-config", "--sandbox", "read-only",
        "--model", model, "--cd", str(run_dir),
        "-c", f'model_reasoning_effort="{effort}"', "-c", "mcp_servers={}",
    ]
    for image in images:
        command.extend(["--image", str(image)])
    command.extend([
        "--output-schema", str(schema), "--json",
        "--output-last-message", str(result_path), prompt,
    ])
    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=run_dir, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )
    events_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        failure = {
            "schema_version": "1.0", "protocol": IDENTIFIABILITY_PROTOCOL,
            "sample_id": sample_id, "replicate": replicate,
            "return_code": completed.returncode,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "events_sha256": sha256_file(events_path),
            "stderr_sha256": sha256_file(stderr_path),
        }
        failure["failure_sha256"] = _canonical_hash(failure, "failure_sha256")
        (run_dir / "failure.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        raise RuntimeError(f"Identifiability probe failed; see {stderr_path}")
    parsed = parse_codex_events(events_path)
    prohibited = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item_type = (event.get("item") or {}).get("type")
        if item_type in PROHIBITED_EVENT_ITEMS:
            prohibited.append(item_type)
    if prohibited:
        raise RuntimeError(f"Identifiability probe used prohibited tools: {sorted(set(prohibited))}")
    value = json.loads(result_path.read_text(encoding="utf-8"))
    validate_probe_result(value, sample_id)
    record = {
        "schema_version": "1.0",
        "protocol": IDENTIFIABILITY_PROTOCOL,
        "replicate": replicate,
        "sample_id": sample_id,
        "model": model,
        "reasoning_effort": effort,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "input_sha256": [sha256_file(image) for image in images],
        "prompt_sha256": sha256_file(prompt_path),
        "result": value,
        "usage": parsed["usage"],
        "provider_errors": parsed["errors"],
        "prohibited_tools_used": [],
    }
    record["record_sha256"] = _canonical_hash(record, "record_sha256")
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return record


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        return [number for item in value for number in _numbers(item)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in _numbers(item)]
    return []


def _workplane_origin(call: dict[str, Any]) -> list[float]:
    arguments = call.get("args") or []
    if not arguments or not isinstance(arguments[0], dict):
        return []
    expression = arguments[0].get("expression")
    if not expression:
        return []
    try:
        parsed = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return []
    if not isinstance(parsed, ast.Call) or not parsed.args:
        return []
    origin = parsed.args[0]
    if not isinstance(origin, ast.Call):
        return []
    values = []
    for arg in origin.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
            values.append(float(arg.value))
        elif (
            isinstance(arg, ast.UnaryOp) and isinstance(arg.op, (ast.UAdd, ast.USub))
            and isinstance(arg.operand, ast.Constant)
            and isinstance(arg.operand.value, (int, float))
        ):
            value = float(arg.operand.value)
            values.append(value if isinstance(arg.op, ast.UAdd) else -value)
    return values


def gt_feature_dimension_values(trajectory: dict[str, Any]) -> list[float]:
    values = []
    for node in trajectory["feature_dag"]["nodes"]:
        if node["kind"] != "feature":
            continue
        values.extend(_numbers(node.get("parameters", {})))
        distance = node.get("parameters", {}).get("distance")
        if node.get("parameters", {}).get("both") is True and isinstance(distance, (int, float)):
            values.append(2.0 * float(distance))
        for call in (node.get("sketch") or {}).get("calls", []):
            values.extend(_numbers(call.get("args", [])))
        workplane_calls = (node.get("workplane") or {}).get("calls", [])
        if workplane_calls:
            values.extend(_workplane_origin(workplane_calls[0]))
    return sorted({round(abs(value), 12) for value in values if abs(value) > 1e-8})


def _matches_displayed(value: float, dimension: dict[str, Any]) -> bool:
    tolerance = 0.5 * (10 ** -int(dimension["decimal_places"])) + 1e-12
    return abs(value - abs(float(dimension["numeric_value"]))) <= tolerance


def build_identifiability_assessment(
    trajectory: dict[str, Any],
    records: list[dict[str, Any]],
    self_check: dict[str, Any],
) -> dict[str, Any]:
    if not records:
        raise ValueError("At least one identifiability record is required")
    dimension_support: Counter[tuple[str, float, int, str]] = Counter()
    for record in records:
        for dimension in record["result"]["explicit_dimensions"]:
            dimension_support[(
                dimension["displayed_text"], float(dimension["numeric_value"]),
                int(dimension["decimal_places"]), dimension["quantity"],
            )] += 1
    consensus = [
        {
            "displayed_text": key[0], "numeric_value": key[1],
            "decimal_places": key[2], "quantity": key[3],
            "support": support, "replicates": len(records),
        }
        for key, support in sorted(dimension_support.items())
        if support > len(records) / 2
    ]
    gt_values = gt_feature_dimension_values(trajectory)
    matched = [value for value in gt_values if any(_matches_displayed(value, item) for item in consensus)]
    hidden = [value for value in gt_values if value not in matched]
    model_complete_votes = sum(record["result"]["dimensionally_complete"] for record in records)
    return {
        "schema_version": "1.0",
        "protocol": IDENTIFIABILITY_PROTOCOL,
        "sample_id": trajectory["sample_id"],
        "replicates": len(records),
        "consensus_explicit_dimensions": consensus,
        "gt_feature_dimension_values": gt_values,
        "gt_values_matched_by_explicit_dimensions": matched,
        "gt_values_without_explicit_dimension_match": hidden,
        "explicit_parameter_coverage": round(len(matched) / len(gt_values), 4) if gt_values else None,
        "model_dimensionally_complete_votes": model_complete_votes,
        "dimensionally_complete_for_exact_reconstruction": bool(
            not hidden and model_complete_votes > len(records) / 2
        ),
        "ground_truth_self_score": self_check["score"],
        "attribution_implication": (
            "Input specification is incomplete at GT parameter precision; a perception-oracle "
            "contrast conflates missing specification with Agent and model perception errors."
            if hidden else
            "All extracted GT feature values match explicit dimensions; perception ownership tests are eligible."
        ),
        "limitations": [
            "A visible silhouette can constrain unlabeled proportions approximately, but not certify the hidden source parameter at printed precision.",
            "GT feature programs may contain dependent coordinates, so coverage is descriptive rather than a degrees-of-freedom proof.",
        ],
    }


def run_input_identifiability_probe(
    manifest: str | Path,
    sample_id: str,
    output_dir: str | Path,
    *,
    model: str = "gpt-5.6-sol",
    effort: str = "medium",
    executable: str | None = None,
    replicates: int = 3,
    timeout: int = 300,
    sample_count: int = 4000,
    voxel_resolution: int = 40,
) -> dict[str, Any]:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    manifest_path, manifest_value = load_geometry_manifest(manifest)
    manifest_path = _workspace_path(manifest_path)
    sample = next((row for row in manifest_value["samples"] if row["sample_id"] == sample_id), None)
    if sample is None:
        raise ValueError(f"Unknown geometry sample: {sample_id}")
    if not sample.get("ground_truth_code"):
        raise ValueError(f"Sample has no GT construction program: {sample_id}")
    output_dir = _workspace_path(output_dir, must_exist=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    images = [(manifest_path.parent / relative).resolve() for relative in sample["input_images"]]
    for image in images:
        _workspace_path(image)
    executable = executable or shutil.which("codex")
    if not executable:
        raise FileNotFoundError("codex executable was not found")
    records = [
        _run_probe_once(
            sample_id=sample_id, images=images, output_dir=output_dir,
            model=model, effort=effort, executable=executable,
            timeout=timeout, replicate=replicate,
        )
        for replicate in range(1, replicates + 1)
    ]
    trajectory = extract_gt_feature_trajectory(
        manifest_path.parent / sample["ground_truth_code"], sample_id=sample_id,
        ground_truth_step=manifest_path.parent / sample["ground_truth_step"],
    )
    self_check = verify_ground_truth_self_consistency(
        manifest_path.parent / sample["ground_truth_step"],
        sample_count=sample_count, voxel_resolution=voxel_resolution,
    )
    assessment = build_identifiability_assessment(trajectory, records, self_check)
    assessment.update({
        "source_manifest_sha256": sha256_file(manifest_path),
        "model": model,
        "reasoning_effort": effort,
        "record_sha256s": [record["record_sha256"] for record in records],
        "source_hashes": {
            path.relative_to(project_root()).as_posix(): sha256_file(path)
            for path in (
                Path(__file__).resolve(),
                Path(__file__).with_name("gt_trajectory.py"),
                project_root() / "src/cad_evoloop/evaluation/schemas/input-identifiability.schema.json",
                project_root() / "evals/geometry-benchmarks/gt-attribution-v1.json",
            )
        },
    })
    assessment["assessment_sha256"] = _canonical_hash(assessment, "assessment_sha256")
    path = output_dir / "identifiability-assessment.json"
    path.write_text(json.dumps(assessment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return assessment
