"""Verify an extracted AutoCAD scene against a CAD 1000 Hours task."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
import sys
from typing import Any

if __package__:
    from .extract_autocad import extract_dwg
    from .extract_core_console import extract_dwg_core
else:  # Supports verifier launch by absolute script path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from cad_evoloop.verification.extract_autocad import extract_dwg
    from cad_evoloop.verification.extract_core_console import extract_dwg_core


DIMENSION_TYPES = ("Dimension", "AcDbDim")
TEXT_TYPES = {"AcDbText", "AcDbMText", "AcDbAttribute", "AcDbAttributeDefinition"}
HATCH_TYPES = {"AcDbHatch"}
SOLID_TYPES = {"AcDb3dSolid", "AcDbBody"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def numeric_measurement(measurement: str) -> tuple[float, str] | None:
    match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s+(.+?)\s*$", measurement)
    if not match:
        return None
    return float(match.group(1)), match.group(2).lower()


def dimension_values(scene: dict[str, Any]) -> list[float]:
    values = []
    for entity in scene.get("entities", []):
        if any(token in entity.get("type", "") for token in DIMENSION_TYPES):
            value = entity.get("Measurement")
            if isinstance(value, (int, float)) and math.isfinite(value):
                values.append(float(value))
    return values


def match_dimensions(task: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    available = dimension_values(scene)
    results = []
    for item in task.get("dimensions", []):
        parsed = numeric_measurement(str(item.get("measurement", "")))
        if not parsed:
            results.append({"id": item.get("id"), "status": "unverified", "reason": "unparsed measurement"})
            continue
        target, unit = parsed
        if "radian" in unit:
            tolerance = max(1e-3, abs(target) * 1e-3)
        elif "degree" in unit:
            tolerance = max(0.1, abs(target) * 1e-3)
        else:
            tolerance = max(0.1, abs(target) * 1e-3)
        if not available:
            results.append({
                "id": item.get("id"), "element": item.get("element"), "target": target,
                "unit": unit, "tolerance": tolerance, "status": "fail", "reason": "no unmatched native dimension",
            })
            continue
        index = min(range(len(available)), key=lambda idx: abs(available[idx] - target))
        actual = available[index]
        error = abs(actual - target)
        status = "pass" if error <= tolerance else "fail"
        if status == "pass":
            available.pop(index)
        results.append({
            "id": item.get("id"), "element": item.get("element"), "target": target,
            "actual": actual, "unit": unit, "tolerance": tolerance,
            "absolute_error": error, "status": status,
        })
    return results


def scene_text(scene: dict[str, Any]) -> str:
    values = []
    for entity in scene.get("entities", []):
        if entity.get("type") in TEXT_TYPES and entity.get("TextString"):
            values.append(str(entity["TextString"]))
    return "\n".join(values).casefold()


def quoted_phrases(requirement: str) -> list[str]:
    phrases = re.findall(r'["“”](.*?)["“”]', requirement)
    return [phrase.strip(" .,") for phrase in phrases if len(phrase.strip()) >= 3]


def evaluate_rubric(requirement: str, scene: dict[str, Any]) -> tuple[str, list[str]]:
    lower = requirement.casefold()
    types = scene.get("summary", {}).get("type_counts", {})
    type_names = set(types)
    texts = scene_text(scene)
    checks: list[tuple[bool, str]] = []

    phrases = quoted_phrases(requirement)
    if phrases:
        present = [phrase for phrase in phrases if phrase.casefold() in texts]
        checks.append((bool(present), f"found labels: {present}" if present else f"missing labels: {phrases}"))
    if "hatch" in lower or "ansi31" in lower:
        count = sum(types.get(name, 0) for name in HATCH_TYPES)
        checks.append((count > 0, f"hatch entities: {count}"))
    if "dimension" in lower or "annotation" in lower:
        count = sum(count for name, count in types.items() if any(token in name for token in DIMENSION_TYPES))
        checks.append((count > 0, f"dimension entities: {count}"))
    if "3d solid" in lower or "single solid" in lower:
        count = sum(types.get(name, 0) for name in SOLID_TYPES)
        expected_single = "single" in lower
        checks.append((count == 1 if expected_single else count > 0, f"3D solids: {count}"))
    if "circle" in lower:
        count = types.get("AcDbCircle", 0)
        checks.append((count > 0, f"circles: {count}"))
    if "arc" in lower:
        count = types.get("AcDbArc", 0)
        checks.append((count > 0, f"arcs: {count}"))
    if re.search(r"\blayer\s+0\b", lower):
        model_entities = [
            entity for entity in scene.get("entities", [])
            if entity.get("owner") == "Model"
        ]
        off_layer = [
            str(entity.get("Handle", entity.get("type", "unknown")))
            for entity in model_entities if str(entity.get("Layer", "")).casefold() != "0"
        ]
        checks.append((bool(model_entities) and not off_layer, f"model entities off Layer 0: {off_layer}"))
    elif "layer" in lower:
        count = len(scene.get("layers", []))
        checks.append((count > 1, f"layers: {count}"))
    if "layout" in lower or "paper-space" in lower or "paper space" in lower:
        paper = [layout for layout in scene.get("layouts", []) if not layout.get("model_type")]
        checks.append((any(layout.get("entity_count", 0) > 0 for layout in paper), f"paper layouts: {len(paper)}"))

    if not checks:
        return "unverified", []
    return ("pass" if all(check[0] for check in checks) else "fail"), [evidence for _, evidence in checks]


def verify_scene(task: dict[str, Any], rubrics: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    summary = scene.get("summary", {})
    hard_gates = [
        {"id": "document_nonempty", "status": "pass" if summary.get("entity_count", 0) > 0 else "fail"},
        {"id": "command_idle", "status": "pass" if not scene.get("active_command") else "fail", "actual": scene.get("active_command")},
        {"id": "extraction_clean", "status": "pass" if summary.get("extraction_errors", 0) == 0 else "fail", "actual": summary.get("extraction_errors", 0)},
    ]
    dimensions = match_dimensions(task, scene)
    rubric_results = []
    for rubric in rubrics.get("rubrics", []):
        status, evidence = evaluate_rubric(str(rubric.get("requirement", "")), scene)
        rubric_results.append({
            "id": rubric.get("id"), "requirement": rubric.get("requirement"),
            "status": status, "evidence": evidence,
        })

    verified = hard_gates + [item for item in dimensions if item["status"] != "unverified"] + [item for item in rubric_results if item["status"] != "unverified"]
    passed = sum(item["status"] == "pass" for item in verified)
    total_checks = len(hard_gates) + len(dimensions) + len(rubric_results)
    score = 100.0 * passed / len(verified) if verified else 0.0
    coverage = 100.0 * len(verified) / total_checks if total_checks else 0.0
    return {
        "schema_version": "0.1",
        "passed": (
            all(item["status"] == "pass" for item in hard_gates)
            and all(item["status"] != "fail" for item in dimensions)
            and all(item["status"] != "fail" for item in rubric_results)
        ),
        "score": round(score, 2),
        "coverage": round(coverage, 2),
        "hard_gates": hard_gates,
        "dimensions": dimensions,
        "rubrics": rubric_results,
        "scene_summary": summary,
        "limitations": [
            "Dimension matching checks native dimension values but does not yet bind each value to a semantic feature.",
            "Natural-language rubrics without deterministic evidence remain unverified and do not affect the score.",
            "Reference-DWG geometry and rendered-view comparison are not included in schema version 0.1.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-dir", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate-dwg", type=Path)
    source.add_argument("--scene-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-autocad", action="store_true")
    parser.add_argument("--core-console", action="store_true")
    parser.add_argument("--write-scene", type=Path)
    args = parser.parse_args()

    task = load_json(args.sample_dir / "task_desc.json")
    rubrics = load_json(args.sample_dir / "rubrics.json")
    if args.scene_json:
        scene = load_json(args.scene_json)
    else:
        scene = (
            extract_dwg_core(args.candidate_dwg)
            if args.core_console
            else extract_dwg(args.candidate_dwg, start_autocad=args.start_autocad)
        )
    if args.write_scene:
        args.write_scene.parent.mkdir(parents=True, exist_ok=True)
        args.write_scene.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")

    verdict = verify_scene(task, rubrics, scene)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": verdict["passed"], "score": verdict["score"], "coverage": verdict["coverage"]}))


if __name__ == "__main__":
    main()
