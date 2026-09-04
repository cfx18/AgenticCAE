"""Ground-truth feature trajectories and counterfactual failure attribution."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

from cad_evoloop.ledger.ledger import sha256_file
from cad_evoloop.paths import project_root

from .geometry_campaign import load_geometry_manifest, slug
from .geometry_score import score_geometry_files


TRAJECTORY_PROTOCOL = "evocad-gt-feature-trajectory-v1"
ORACLE_PROTOCOL = "evocad-gt-oracle-context-v1"
ATTRIBUTION_PROTOCOL = "evocad-trajectory-attribution-v1"
ORACLE_LEVELS = ("perception", "plan")


def _canonical_hash(value: dict[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _workspace_path(path: str | Path, *, must_exist: bool = True) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(project_root().resolve())
    except ValueError as exc:
        raise ValueError(f"Path must remain inside the workspace: {resolved}") from exc
    if must_exist and not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def _names(node: ast.AST) -> list[str]:
    return sorted({
        item.id for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and item.id != "cq"
    })


def _literal(node: ast.AST) -> Any:
    """Serialize an expression without evaluating dataset code."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {
            str(_literal(key)): _literal(value)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _literal(node.operand)
        if isinstance(value, (int, float)):
            return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Name):
        return {"ref": node.id}
    return {"expression": ast.unparse(node)}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ast.unparse(node)


def _flatten_calls(node: ast.AST) -> tuple[ast.AST, list[dict[str, Any]]]:
    """Return the base expression and method/function calls in execution order."""
    calls: list[dict[str, Any]] = []

    def visit(current: ast.AST) -> ast.AST:
        if not isinstance(current, ast.Call):
            return current
        if isinstance(current.func, ast.Attribute):
            base = visit(current.func.value)
            name = current.func.attr
        else:
            base = current.func
            name = _call_name(current.func)
        calls.append({
            "method": name,
            "args": [_literal(arg) for arg in current.args],
            "kwargs": {keyword.arg or "**": _literal(keyword.value) for keyword in current.keywords},
        })
        return base

    return visit(node), calls


def _assignment_rows(tree: ast.Module, source: str) -> list[dict[str, Any]]:
    rows = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target_node = statement.targets[0]
        if not isinstance(target_node, ast.Name):
            continue
        base, calls = _flatten_calls(statement.value)
        rows.append({
            "statement_id": f"s{len(rows) + 1:03d}",
            "target": target_node.id,
            "line_start": statement.lineno,
            "line_end": statement.end_lineno or statement.lineno,
            "expression": ast.get_source_segment(source, statement.value) or ast.unparse(statement.value),
            "base": _call_name(base),
            "dependencies": _names(statement.value),
            "calls": calls,
        })
    return rows


def _call(row: dict[str, Any], method: str) -> dict[str, Any] | None:
    return next((item for item in row["calls"] if item["method"] == method), None)


def _resolved_dependencies(
    name: str, assignments: dict[str, dict[str, Any]], seen: set[str] | None = None,
) -> list[str]:
    seen = set(seen or ())
    if name in seen or name not in assignments:
        return []
    seen.add(name)
    row = assignments[name]
    result = [name]
    for dependency in row["dependencies"]:
        result.extend(_resolved_dependencies(dependency, assignments, seen))
    return list(dict.fromkeys(result))


def extract_gt_feature_trajectory(
    source_path: str | Path,
    *,
    sample_id: str,
    ground_truth_step: str | Path | None = None,
) -> dict[str, Any]:
    """Parse a CadQuery GT program into a feature DAG without executing it."""
    source_path = _workspace_path(source_path)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    assignments = _assignment_rows(tree, source)
    latest_assignment: dict[str, dict[str, Any]] = {}
    feature_nodes: list[dict[str, Any]] = []
    producer: dict[str, str] = {}
    checkpoints: list[dict[str, Any]] = []
    for row in assignments:
        target = row["target"]
        extrude = _call(row, "extrude")
        boolean = next((
            item for item in row["calls"] if item["method"] in {"union", "cut", "intersect"}
        ), None)
        if extrude is not None:
            referenced = []
            for dependency in row["dependencies"]:
                referenced.extend(_resolved_dependencies(dependency, latest_assignment))
            source_rows = [latest_assignment[name] for name in dict.fromkeys(referenced)]
            workplane = next((item for item in source_rows if _call(item, "Workplane")), None)
            sketch = next((
                item for item in source_rows
                if any(call["method"] in {
                    "moveTo", "lineTo", "threePointArc", "sagittaArc", "radiusArc",
                    "circle", "rect", "polygon", "spline", "close",
                } for call in item["calls"])
            ), None)
            node_id = f"f{sum(item['kind'] == 'feature' for item in feature_nodes) + 1:03d}"
            node = {
                "node_id": node_id,
                "kind": "feature",
                "operation": "extrude",
                "output": target,
                "parents": [],
                "source_statement": row["statement_id"],
                "workplane": ({
                    "variable": workplane["target"],
                    "calls": workplane["calls"],
                } if workplane else None),
                "sketch": ({
                    "variable": sketch["target"],
                    "calls": sketch["calls"],
                } if sketch else None),
                "feature_calls": row["calls"],
                "parameters": {
                    "distance": extrude["args"][0] if extrude["args"] else None,
                    **extrude["kwargs"],
                },
            }
            feature_nodes.append(node)
            producer[target] = node_id
            latest_assignment[target] = row
            continue
        if boolean is not None:
            dependencies = [producer[name] for name in row["dependencies"] if name in producer]
            node_id = f"b{sum(item['kind'] == 'boolean' for item in feature_nodes) + 1:03d}"
            node = {
                "node_id": node_id,
                "kind": "boolean",
                "operation": boolean["method"],
                "output": target,
                "parents": list(dict.fromkeys(dependencies)),
                "source_statement": row["statement_id"],
                "parameters": {"operands": boolean["args"]},
            }
            feature_nodes.append(node)
            producer[target] = node_id
            if target == "solid":
                checkpoints.append({
                    "checkpoint_id": f"c{len(checkpoints) + 1:03d}",
                    "after_node": node_id,
                    "source_statement": row["statement_id"],
                })
            latest_assignment[target] = row
            continue
        if len(row["dependencies"]) == 1:
            source_name = row["dependencies"][0]
            if source_name in producer:
                producer[target] = producer[source_name]
                if target == "solid":
                    checkpoints.append({
                        "checkpoint_id": f"c{len(checkpoints) + 1:03d}",
                        "after_node": producer[target],
                        "source_statement": row["statement_id"],
                    })
        latest_assignment[target] = row

    if not feature_nodes or "solid" not in producer:
        raise ValueError(f"No final CadQuery solid feature trajectory found: {source_path}")
    step_path = _workspace_path(ground_truth_step) if ground_truth_step else None
    value = {
        "schema_version": "1.0",
        "protocol": TRAJECTORY_PROTOCOL,
        "sample_id": sample_id,
        "extractor": "static-python-ast-no-execution",
        "source": {
            "path": source_path.relative_to(project_root()).as_posix(),
            "sha256": sha256_file(source_path),
        },
        "ground_truth_step": ({
            "path": step_path.relative_to(project_root()).as_posix(),
            "sha256": sha256_file(step_path),
        } if step_path else None),
        "feature_dag": {
            "nodes": feature_nodes,
            "final_node": producer["solid"],
            "node_count": len(feature_nodes),
        },
        "checkpoints": checkpoints,
        "static_assignments": assignments,
        "limitations": [
            "The AST is a reference feature program, not a unique optimal construction trajectory.",
            "Static extraction does not prove that the source executes in the current runtime.",
        ],
    }
    value["trajectory_sha256"] = _canonical_hash(value, "trajectory_sha256")
    return value


def _agent_feature(node: dict[str, Any]) -> dict[str, Any]:
    feature = {
        "operation": node["operation"],
        "workplane_calls": (node.get("workplane") or {}).get("calls", []),
        "sketch_calls": (node.get("sketch") or {}).get("calls", []),
        "feature_calls": [
            call for call in node.get("feature_calls", []) if call["method"] != "add"
        ],
        "parameters": node.get("parameters", {}),
    }
    feature["feature_token"] = hashlib.sha256(
        json.dumps(feature, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return feature


def oracle_packet(trajectory: dict[str, Any], level: str) -> dict[str, Any]:
    if level not in ORACLE_LEVELS:
        raise ValueError(f"Unsupported oracle level: {level}")
    nodes = trajectory["feature_dag"]["nodes"]
    features = [_agent_feature(node) for node in nodes if node["kind"] == "feature"]
    packet: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol": ORACLE_PROTOCOL,
        "sample_id": trajectory["sample_id"],
        "oracle_level": level,
        "evaluation_only_intervention": True,
        "instruction": (
            "Use this exact evaluator-provided geometric information to construct the candidate. "
            "Do not inspect any ground-truth file or infer information outside this packet."
        ),
    }
    if level == "perception":
        packet["unordered_exact_features"] = sorted(
            features, key=lambda feature: feature["feature_token"],
        )
        packet["withheld"] = ["feature order", "Boolean plan", "executable source"]
    else:
        packet["ordered_stages"] = [
            {
                "stage": index,
                "node_id": node["node_id"],
                **(_agent_feature(node) if node["kind"] == "feature" else {
                    "operation": node["operation"],
                    "parents": node["parents"],
                    "parameters": node["parameters"],
                }),
            }
            for index, node in enumerate(nodes, 1)
        ]
        packet["withheld"] = ["executable source", "ground-truth CAD/mesh"]
    packet["oracle_packet_sha256"] = _canonical_hash(packet, "oracle_packet_sha256")
    return packet


def extract_manifest_trajectories(
    manifest: str | Path,
    output_dir: str | Path,
    *,
    sample_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    manifest_path, manifest_value = load_geometry_manifest(manifest)
    manifest_path = _workspace_path(manifest_path)
    output_dir = _workspace_path(output_dir, must_exist=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = set(sample_ids or ())
    selected = [
        sample for sample in manifest_value["samples"]
        if not requested or sample["sample_id"] in requested
    ]
    missing = requested - {sample["sample_id"] for sample in selected}
    if missing:
        raise ValueError(f"Unknown geometry samples: {sorted(missing)}")
    samples: dict[str, Any] = {}
    trajectory_dir = output_dir / "trajectories"
    trajectory_dir.mkdir(exist_ok=True)
    for sample in selected:
        code = sample.get("ground_truth_code")
        if not code:
            continue
        source = manifest_path.parent / code
        step = manifest_path.parent / sample["ground_truth_step"]
        trajectory = extract_gt_feature_trajectory(
            source, sample_id=sample["sample_id"], ground_truth_step=step,
        )
        destination = trajectory_dir / f"{slug(sample['sample_id'])}.json"
        destination.write_text(
            json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        samples[sample["sample_id"]] = {
            "trajectory": destination.relative_to(output_dir).as_posix(),
            "trajectory_sha256": trajectory["trajectory_sha256"],
            "perception": oracle_packet(trajectory, "perception"),
            "plan": oracle_packet(trajectory, "plan"),
        }
    oracle = {
        "schema_version": "1.0",
        "protocol": ORACLE_PROTOCOL,
        "source_manifest": manifest_path.relative_to(project_root()).as_posix(),
        "source_manifest_sha256": sha256_file(manifest_path),
        "sample_ids": sorted(samples),
        "sample_count": len(samples),
        "samples": samples,
    }
    oracle["oracle_manifest_sha256"] = _canonical_hash(oracle, "oracle_manifest_sha256")
    oracle_path = output_dir / "oracle-context.json"
    oracle_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    experiment_plan = {
        "schema_version": "1.0",
        "protocol": ATTRIBUTION_PROTOCOL,
        "design": "fixed-model paired oracle ladder",
        "conditions": [
            {
                "condition": "normal",
                "agent_input": "images plus verifier feedback",
                "purpose": "Measure end-to-end Agent performance",
            },
            {
                "condition": "perception",
                "agent_input": "normal inputs plus unordered exact feature inventory",
                "purpose": "Remove image interpretation error while preserving planning",
                "oracle_level": "perception",
            },
            {
                "condition": "plan",
                "agent_input": "normal inputs plus ordered exact feature DAG",
                "purpose": "Remove perception and planning error while preserving tool use",
                "oracle_level": "plan",
            },
            {
                "condition": "executor",
                "agent_input": None,
                "purpose": "Replay GT code directly to test data, execution, and verifier compatibility",
            },
        ],
        "controls": {
            "fixed": ["sample", "gpt-5.6-sol", "reasoning effort", "tools", "verifier", "budgets"],
            "replicates_per_agent_condition": 3,
            "report_each_condition_separately": True,
            "normal_scores_must_never_include_oracle_runs": True,
        },
        "oracle_context": oracle_path.relative_to(project_root()).as_posix(),
    }
    experiment_plan["experiment_plan_sha256"] = _canonical_hash(
        experiment_plan, "experiment_plan_sha256",
    )
    (output_dir / "experiment-plan.json").write_text(
        json.dumps(experiment_plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    summary = {
        "protocol": TRAJECTORY_PROTOCOL,
        "requested_samples": len(selected),
        "extracted_samples": len(samples),
        "skipped_without_code": len(selected) - len(samples),
        "oracle_context": oracle_path.relative_to(project_root()).as_posix(),
        "oracle_manifest_sha256": oracle["oracle_manifest_sha256"],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return summary


def load_oracle_context(path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = _workspace_path(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("protocol") != ORACLE_PROTOCOL:
        raise ValueError("Unsupported GT oracle context")
    if value.get("sample_count") != len(value.get("samples", {})):
        raise ValueError("Oracle context sample count mismatch")
    if value.get("sample_ids") != sorted(value.get("samples", {})):
        raise ValueError("Oracle context sample identifiers mismatch")
    if value.get("oracle_manifest_sha256") != _canonical_hash(value, "oracle_manifest_sha256"):
        raise ValueError("Oracle context digest mismatch")
    return path, value


def validate_oracle_packet(packet: dict[str, Any], sample_id: str, level: str) -> None:
    if packet.get("protocol") != ORACLE_PROTOCOL:
        raise ValueError("Unsupported oracle packet")
    if packet.get("sample_id") != sample_id or packet.get("oracle_level") != level:
        raise ValueError("Oracle packet is bound to a different sample or level")
    if packet.get("oracle_packet_sha256") != _canonical_hash(packet, "oracle_packet_sha256"):
        raise ValueError("Oracle packet digest mismatch")


def _cadquery_available(executable: Path) -> bool:
    completed = subprocess.run(
        [str(executable), "-c", "import cadquery"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return completed.returncode == 0


def _instrumented_source(source: str, checkpoint_dir: Path) -> tuple[str, list[str]]:
    tree = ast.parse(source)
    body: list[ast.stmt] = []
    checkpoints = []
    for statement in tree.body:
        body.append(statement)
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "solid" for target in statement.targets):
            continue
        checkpoint = checkpoint_dir / f"checkpoint-{len(checkpoints) + 1:03d}.step"
        checkpoints.append(str(checkpoint))
        expression = ast.Expr(value=ast.Call(
            func=ast.Attribute(
                value=ast.Attribute(value=ast.Name(id="cq", ctx=ast.Load()), attr="exporters", ctx=ast.Load()),
                attr="export", ctx=ast.Load(),
            ),
            args=[ast.Name(id="solid", ctx=ast.Load()), ast.Constant(value=str(checkpoint))],
            keywords=[],
        ))
        body.append(ast.copy_location(expression, statement))
    tree.body = body
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", checkpoints


def replay_gt_trajectory(
    source_path: str | Path,
    ground_truth_step: str | Path,
    output_dir: str | Path,
    *,
    python_executable: str | Path | None = None,
    timeout: int = 300,
    sample_count: int = 4000,
    voxel_resolution: int = 40,
) -> dict[str, Any]:
    """Opt-in executable replay. Static extraction never calls this function."""
    source_path = _workspace_path(source_path)
    ground_truth_step = _workspace_path(ground_truth_step)
    output_dir = _workspace_path(output_dir, must_exist=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = Path(python_executable or sys.executable).resolve()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol": TRAJECTORY_PROTOCOL,
        "mode": "oracle_executor_replay",
        "source_sha256": sha256_file(source_path),
        "ground_truth_sha256": sha256_file(ground_truth_step),
        "python_executable": executable.as_posix(),
    }
    if not _cadquery_available(executable):
        result.update({
            "status": "unavailable",
            "missing_dependency": "cadquery",
            "passed": None,
            "score": None,
        })
    else:
        checkpoint_dir = output_dir / "checkpoints"
        checkpoint_dir.mkdir(exist_ok=True)
        instrumented, checkpoints = _instrumented_source(
            source_path.read_text(encoding="utf-8"), checkpoint_dir,
        )
        replay_path = output_dir / "instrumented_ground_truth.py"
        replay_path.write_text(instrumented, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [str(executable), str(replay_path)], cwd=output_dir,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        final_path = Path(checkpoints[-1]) if checkpoints else None
        result.update({
            "return_code": completed.returncode,
            "stderr": completed.stderr[-4000:],
            "checkpoint_count": sum(Path(path).is_file() for path in checkpoints),
            "expected_checkpoint_count": len(checkpoints),
        })
        if completed.returncode == 0 and final_path and final_path.is_file():
            score = score_geometry_files(
                final_path, ground_truth_step,
                sample_count=sample_count, voxel_resolution=voxel_resolution,
            )
            result.update({"status": "completed", "passed": score["passed"], "score": score["score"], "verdict": score})
        else:
            result.update({"status": "failed", "passed": False, "score": 0.0})
    result["replay_sha256"] = _canonical_hash(result, "replay_sha256")
    (output_dir / "replay-result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return result


def verify_ground_truth_self_consistency(
    ground_truth_step: str | Path,
    *,
    sample_count: int = 4000,
    voxel_resolution: int = 40,
) -> dict[str, Any]:
    path = _workspace_path(ground_truth_step)
    result = score_geometry_files(
        path, path, sample_count=sample_count, voxel_resolution=voxel_resolution,
    )
    return {
        "status": "completed",
        "passed": result["passed"],
        "score": result["score"],
        "step_sha256": sha256_file(path),
        "verdict": result,
    }


def infer_failure_attribution(
    conditions: dict[str, dict[str, Any] | None],
    ground_truth_self_check: dict[str, Any],
) -> dict[str, Any]:
    """Apply the preregistered oracle ladder without overclaiming model causality."""
    available = {
        name: value for name, value in conditions.items()
        if value is not None and isinstance(value.get("passed"), bool)
    }
    missing = [name for name in ("normal", "perception", "plan", "executor") if name not in available]
    if not ground_truth_self_check.get("passed"):
        return {
            "status": "identified",
            "primary_layer": "benchmark_or_verifier",
            "claim": "The ground-truth artifact does not pass the frozen verifier against itself.",
            "missing_conditions": missing,
        }
    normal = available.get("normal")
    if normal is None:
        return {
            "status": "not_identified", "primary_layer": None,
            "claim": "The normal Agent condition is required as the observational baseline.",
            "missing_conditions": ["normal"],
        }
    if normal.get("passed"):
        return {
            "status": "no_failure",
            "primary_layer": None,
            "claim": "The normal Agent condition already satisfies the strict contract.",
            "missing_conditions": missing,
        }
    perception = available.get("perception")
    if perception is None:
        return {
            "status": "not_identified",
            "primary_layer": None,
            "claim": (
                "The observational trajectory localizes what went wrong but cannot distinguish "
                "Agent design from model capability without the missing oracle interventions."
            ),
            "missing_conditions": ["perception"],
        }
    if perception.get("passed"):
        return {
            "status": "identified",
            "primary_layer": "observation_to_feature_inference",
            "claim": "Exact features pass while the normal image-to-feature path fails under the same model and tools.",
            "missing_conditions": [],
            "agent_vs_model_ownership": {
                "status": "not_identified",
                "claim": "The oracle removes both Agent observation design and model visual inference error.",
                "required_controls": [
                    "same_model_alternate_perception_policy",
                    "fixed_agent_alternate_model",
                ],
            },
        }
    plan = available.get("plan")
    if plan is None:
        return {
            "status": "not_identified", "primary_layer": None,
            "claim": "Perception remains insufficient; the plan intervention is required next.",
            "missing_conditions": ["plan"],
        }
    if plan.get("passed"):
        return {
            "status": "identified",
            "primary_layer": "planning_policy",
            "claim": "The exact plan passes, but an unordered exact feature inventory does not.",
            "missing_conditions": [],
            "agent_vs_model_ownership": {
                "status": "not_identified",
                "claim": "The contrast localizes planning but does not separate policy scaffolding from model reasoning capacity.",
                "required_controls": [
                    "same_model_alternate_planning_policy",
                    "fixed_agent_alternate_model",
                ],
            },
        }
    executor = available.get("executor")
    if executor is None:
        return {
            "status": "not_identified", "primary_layer": None,
            "claim": "The exact plan still fails; direct execution is required to isolate the remaining layer.",
            "missing_conditions": ["executor"],
        }
    if executor.get("passed"):
        return {
            "status": "partially_identified",
            "primary_layer": "model_tool_use_or_action_translation",
            "claim": (
                "Direct execution passes but the fixed model cannot realize an exact ordered plan. "
                "Separate model/tool-use limitations from prompt translation with an alternate executor policy."
            ),
            "missing_conditions": [],
            "agent_vs_model_ownership": {
                "status": "not_identified",
                "required_controls": ["same_model_alternate_action_translation"],
            },
        }
    return {
        "status": "identified",
        "primary_layer": "executor_or_cad_interface",
        "claim": "Exact GT execution fails, so model-level attribution is not valid.",
        "missing_conditions": [],
        "agent_vs_model_ownership": {
            "status": "infrastructure_first",
            "required_controls": [],
        },
    }


def _load_result(path: str | Path, sample_id: str) -> dict[str, Any]:
    path = _workspace_path(path)
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("sample_id") == sample_id:
            return value
        rows = value if isinstance(value, list) else value.get("results", [])
    else:
        direct = list(path.rglob("result.json"))
        rows = []
        for result_path in direct:
            value = json.loads(result_path.read_text(encoding="utf-8"))
            if value.get("sample_id") == sample_id:
                return value
        for name in ("results.json", "agent-results.json"):
            candidate = path / name
            if candidate.is_file():
                rows = json.loads(candidate.read_text(encoding="utf-8"))
                break
    for row in rows:
        if row.get("sample_id") != sample_id:
            continue
        if row.get("result"):
            return _load_result(row["result"], sample_id)
        return row
    raise ValueError(f"No result for {sample_id} under {path}")


def _condition_summary(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts") or []
    return {
        "campaign": result.get("campaign"),
        "model": result.get("model"),
        "score": float(result.get("score", 0.0)),
        "passed": bool(result.get("passed")),
        "attempts": len(attempts),
        "first_score": float(attempts[0].get("score", 0.0)) if attempts else None,
        "selected_attempt_id": result.get("selected_attempt_id"),
        "stop_reason": result.get("stop_reason"),
        "agent_requested_continue": result.get("agent_requested_continue"),
    }


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in _numbers(item)]
    if isinstance(value, list):
        return [number for item in value for number in _numbers(item)]
    return []


def _trajectory_numeric_literals(trajectory: dict[str, Any]) -> list[float]:
    numbers = _numbers(trajectory["feature_dag"]["nodes"])
    for row in trajectory.get("static_assignments", []):
        try:
            expression = ast.parse(row["expression"], mode="eval")
        except (SyntaxError, TypeError):
            continue
        numbers.extend(
            float(node.value) for node in ast.walk(expression)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        )
    return numbers


def observational_trace_diagnostics(
    result: dict[str, Any] | None,
    trajectory: dict[str, Any],
) -> dict[str, Any] | None:
    """Summarize falsifiable trace facts while keeping causal claims separate."""
    if result is None:
        return None
    attempts = result.get("attempts") or []
    scores = [float(attempt.get("score", 0.0)) for attempt in attempts]
    operation_nodes = []
    failed_rubrics = []
    for attempt in attempts:
        verdict_value = None
        verdict_path = attempt.get("verdict")
        if verdict_path:
            try:
                path = _workspace_path(verdict_path)
                verdict_value = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                verdict_value = None
        if verdict_value is None:
            continue
        graph = (
            verdict_value.get("mismatch", {})
            .get("localization", {})
            .get("native_topology", {})
            .get("boolean_lineage", {})
            .get("operation_graph", {})
        )
        for node in graph.get("nodes", []):
            operation_nodes.append({"attempt_id": attempt.get("attempt_id"), **node})
        if attempt.get("attempt_id") == result.get("selected_attempt_id"):
            failed_rubrics = [
                rubric for rubric in verdict_value.get("rubrics", [])
                if rubric.get("status") != "passed"
            ]
    gt_nodes = trajectory["feature_dag"]["nodes"]
    gt_numbers = sorted(set(
        round(number, 12) for number in _trajectory_numeric_literals(trajectory)
    ))
    agent_numbers = sorted(set(
        round(number, 12)
        for node in operation_nodes for number in _numbers(node.get("parameters", {}))
    ))
    exact_matches = [
        number for number in agent_numbers
        if any(abs(number - reference) <= 1e-9 for reference in gt_numbers)
    ]
    novel = [number for number in agent_numbers if number not in exact_matches]
    regressions = sum(current < previous for previous, current in zip(scores, scores[1:]))
    return {
        "score_history": scores,
        "best_score_gain": round(max(scores) - scores[0], 4) if scores else None,
        "score_regressions": regressions,
        "selected_failed_rubrics": failed_rubrics,
        "runtime_error_messages": sum(len(attempt.get("errors") or []) for attempt in attempts),
        "safety_censored_while_requesting_continue": bool(
            result.get("agent_requested_continue")
            and result.get("stop_reason") in {"max_iterations", "job_time_budget"}
        ),
        "gt_feature_program": {
            "node_count": len(gt_nodes),
            "operation_histogram": {
                operation: sum(node["operation"] == operation for node in gt_nodes)
                for operation in sorted({node["operation"] for node in gt_nodes})
            },
            "checkpoint_count": len(trajectory["checkpoints"]),
        },
        "agent_declared_operations": {
            "count_across_attempt_verdicts": len(operation_nodes),
            "operation_types": sorted({str(node.get("operation_type")) for node in operation_nodes}),
            "feature_ids": sorted({str(node.get("feature_id")) for node in operation_nodes}),
            "numeric_parameters": len(agent_numbers),
            "parameters_exactly_present_in_gt": len(exact_matches),
            "parameter_exact_match_fraction": (
                round(len(exact_matches) / len(agent_numbers), 4) if agent_numbers else None
            ),
            "example_parameters_not_present_in_gt": novel[:20],
        },
        "interpretation": [
            "Invented parameters and score regressions diagnose the realized policy, not the base model alone.",
            "Declared operation manifests are Agent-authored evidence and may be incomplete or semantically different from GT feature nodes.",
            "The GT feature program is one valid construction, not proof that alternative feature sequences are wrong.",
        ],
    }


def _check_experimental_controls(
    raw_results: dict[str, dict[str, Any] | None],
    executor: dict[str, Any] | None,
    trajectory: dict[str, Any],
) -> dict[str, Any]:
    observed = {
        name: {
            "model": result.get("model"),
            "reasoning_effort": result.get("reasoning_effort"),
            "agent_loop_protocol": result.get("agent_loop_protocol"),
        }
        for name, result in raw_results.items() if result is not None
    }
    mismatches = []
    values = list(observed.values())
    if values:
        reference = values[0]
        for name, value in observed.items():
            for field in ("model", "reasoning_effort", "agent_loop_protocol"):
                if value[field] != reference[field]:
                    mismatches.append({
                        "condition": name,
                        "field": field,
                        "expected": reference[field],
                        "actual": value[field],
                    })
    if executor is not None:
        if executor.get("source_sha256") != trajectory["source"]["sha256"]:
            mismatches.append({
                "condition": "executor", "field": "source_sha256",
                "expected": trajectory["source"]["sha256"],
                "actual": executor.get("source_sha256"),
            })
        expected_step = (trajectory.get("ground_truth_step") or {}).get("sha256")
        if executor.get("ground_truth_sha256") != expected_step:
            mismatches.append({
                "condition": "executor", "field": "ground_truth_sha256",
                "expected": expected_step,
                "actual": executor.get("ground_truth_sha256"),
            })
    return {"valid": not mismatches, "observed": observed, "mismatches": mismatches}


def build_attribution_report(
    manifest: str | Path,
    sample_id: str,
    output_dir: str | Path,
    *,
    normal_result: str | Path | None = None,
    perception_result: str | Path | None = None,
    plan_result: str | Path | None = None,
    executor_result: str | Path | None = None,
    sample_count: int = 4000,
    voxel_resolution: int = 40,
) -> dict[str, Any]:
    manifest_path, manifest_value = load_geometry_manifest(manifest)
    sample = next((row for row in manifest_value["samples"] if row["sample_id"] == sample_id), None)
    if sample is None:
        raise ValueError(f"Unknown geometry sample: {sample_id}")
    if not sample.get("ground_truth_code"):
        raise ValueError(f"Sample has no GT construction program: {sample_id}")
    output_dir = _workspace_path(output_dir, must_exist=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    trajectory = extract_gt_feature_trajectory(
        manifest_path.parent / sample["ground_truth_code"],
        sample_id=sample_id,
        ground_truth_step=manifest_path.parent / sample["ground_truth_step"],
    )
    raw_results = {
        "normal": _load_result(normal_result, sample_id) if normal_result else None,
        "perception": _load_result(perception_result, sample_id) if perception_result else None,
        "plan": _load_result(plan_result, sample_id) if plan_result else None,
    }
    conditions: dict[str, dict[str, Any] | None] = {
        "normal": _condition_summary(raw_results["normal"]) if raw_results["normal"] else None,
        "perception": _condition_summary(raw_results["perception"]) if raw_results["perception"] else None,
        "plan": _condition_summary(raw_results["plan"]) if raw_results["plan"] else None,
        "executor": (
            json.loads(_workspace_path(executor_result).read_text(encoding="utf-8"))
            if executor_result else None
        ),
    }
    self_check = verify_ground_truth_self_consistency(
        manifest_path.parent / sample["ground_truth_step"],
        sample_count=sample_count, voxel_resolution=voxel_resolution,
    )
    control_check = _check_experimental_controls(
        raw_results, conditions["executor"], trajectory,
    )
    attribution = infer_failure_attribution(conditions, self_check)
    if not control_check["valid"]:
        attribution = {
            "status": "not_identified",
            "primary_layer": None,
            "claim": "The supplied conditions do not satisfy the fixed experimental controls.",
            "missing_conditions": attribution.get("missing_conditions", []),
            "control_mismatches": control_check["mismatches"],
        }
    attribution["evidence_grade"] = "single_replicate_diagnostic"
    attribution["population_causal_claim_valid"] = False
    report = {
        "schema_version": "1.0",
        "protocol": ATTRIBUTION_PROTOCOL,
        "sample_id": sample_id,
        "source_manifest_sha256": sha256_file(manifest_path),
        "trajectory": trajectory,
        "ground_truth_self_check": self_check,
        "conditions": conditions,
        "observational_diagnostics": observational_trace_diagnostics(
            raw_results["normal"], trajectory,
        ),
        "attribution": attribution,
        "experimental_controls": {
            "fixed": ["sample", "model", "reasoning effort", "tools", "verifier", "budgets"],
            "varied": "oracle information supplied to the same Agent policy",
            "minimum_replicates_per_stochastic_condition": 3,
            "warning": "A single trajectory is diagnostic evidence, not a causal Agent-versus-model estimate.",
            "validation": control_check,
        },
    }
    report["report_sha256"] = _canonical_hash(report, "report_sha256")
    (output_dir / "attribution-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return report
