"""EvoCAD image-feedback loop evaluated by BenchCAD's official scorer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from PIL import Image

from cad_evoloop.agent.models.base import ConversationHandle, ModelRequest
from cad_evoloop.agent.models.codex_cli import CodexCLIConfig, CodexCLIProvider
from cad_evoloop.evaluation.reconstruction_ir import build_reconstruction_ir
from cad_evoloop.paths import project_root


DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason", "next_action", "confidence"],
    "properties": {
        "decision": {"type": "string", "enum": ["continue", "stop"]},
        "reason": {"type": "string"},
        "next_action": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


@dataclass(frozen=True)
class BenchCADConfig:
    upstream: Path
    data_dir: Path
    output: Path
    campaign: str
    model: str = "gpt-5.6-sol"
    effort: str = "medium"
    max_iterations: int = 12
    max_records: int | None = None
    timeout: int = 1800
    exec_timeout: int = 600
    voxel_resolution: int = 64
    reconstruction_mode: str = "forced_ir"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_bridge(python: Path, args: list[str], timeout: int) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [str(python), str(project_root() / "evals/benchcad/official_bridge.py"), *args],
        cwd=project_root(), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, env=env, check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("ok", False)
    payload["return_code"] = result.returncode
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()[-2000:]
    return payload


def _part_mask(image: Image.Image) -> bytearray:
    rgb = image.convert("RGB")
    # Stored BenchCAD corpora use either teal or olive faces. In both palettes
    # the green channel is at least the red channel, while axes/edges are red
    # or orange. Chroma excludes white backgrounds and black panel borders.
    return bytearray(
        1 if g >= r - 5 and max(r, g, b) - min(r, g, b) > 15 and max(r, g, b) < 250 else 0
        for r, g, b in rgb.getdata()
    )


def image_verdict(target_path: Path, candidate_path: Path, overlay_path: Path) -> dict[str, Any]:
    target = Image.open(target_path).convert("RGB")
    candidate = Image.open(candidate_path).convert("RGB")
    if candidate.size != target.size:
        candidate = candidate.resize(target.size)
    truth = _part_mask(target)
    pred = _part_mask(candidate)
    width, height = target.size
    intersection = sum(a and b for a, b in zip(truth, pred))
    union = sum(a or b for a, b in zip(truth, pred))
    truth_area, pred_area = sum(truth), sum(pred)
    missing = sum(a and not b for a, b in zip(truth, pred))
    excess = sum(b and not a for a, b in zip(truth, pred))
    quad_values = []
    for y0, y1 in ((0, height // 2), (height // 2, height)):
        for x0, x1 in ((0, width // 2), (width // 2, width)):
            ti = pi = uu = 0
            for y in range(y0, y1):
                offset = y * width
                for x in range(x0, x1):
                    a, b = truth[offset + x], pred[offset + x]
                    ti += bool(a and b)
                    uu += bool(a or b)
            quad_values.append(round(ti / uu, 6) if uu else 1.0)
    overlay = Image.new("RGB", target.size, "white")
    pixels = []
    for a, b in zip(truth, pred):
        if a and b:
            pixels.append((83, 170, 125))
        elif a:
            pixels.append((55, 126, 184))
        elif b:
            pixels.append((224, 125, 50))
        else:
            pixels.append((248, 248, 248))
    overlay.putdata(pixels)
    overlay.save(overlay_path)
    return {
        "protocol": "evocad-benchcad-image-verifier-v1",
        "gt_geometry_used": False,
        "silhouette_iou": round(intersection / union, 6) if union else 1.0,
        "per_view_silhouette_iou": quad_values,
        "target_pixels": truth_area,
        "candidate_pixels": pred_area,
        "candidate_to_target_area_ratio": round(pred_area / truth_area, 6) if truth_area else None,
        "missing_fraction": round(missing / truth_area, 6) if truth_area else 0.0,
        "excess_fraction": round(excess / truth_area, 6) if truth_area else 0.0,
        "overlay_legend": {"overlap": "green", "missing": "blue", "excess": "orange"},
    }


def _write_run_helper(
    workspace: Path, python: Path, upstream: Path, timeout: int, view_size: int,
) -> None:
    bridge = project_root() / "evals/benchcad/official_bridge.py"
    content = (
        "from pathlib import Path\nimport json, os, subprocess\n"
        f"cmd = [{str(python)!r}, {str(bridge)!r}, '--upstream', {str(upstream)!r}, "
        f"'execute', '--code', 'candidate.py', '--step', 'candidate.step', "
        f"'--render', 'candidate.png', '--timeout', {str(timeout)!r}, "
        f"'--parallel-scale', '0.55', '--view-size', {str(view_size)!r}]\n"
        "env = dict(os.environ); env['PYTHONUTF8'] = '1'\n"
        "p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)\n"
        "print(p.stdout.strip())\n"
        "if p.stderr.strip(): print(p.stderr.strip())\n"
        "raise SystemExit(p.returncode)\n"
    )
    (workspace / "run_candidate.py").write_text(content, encoding="utf-8", newline="\n")


def _audit_invocation(turn: Any, forbidden: list[str]) -> dict[str, Any]:
    events = Path(turn.provider_metadata.get("artifacts", {}).get("events", ""))
    text = events.read_text(encoding="utf-8", errors="replace") if events.is_file() else ""
    hits = [value for value in forbidden if value and value.lower() in text.lower()]
    commands: list[str] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "command_execution" and isinstance(item.get("command"), str):
            commands.append(item["command"])
    command_text = "\n".join(commands).lower()
    traversal = bool(
        re.search(r"(?<!\.)\.\.[\\/]", command_text)
        or re.search(r"\b(?:get-childitem|ls|dir)\s+['\"]?\.\.(?:\s|['\"]|$)", command_text)
    )
    return {"passed": not hits and not traversal, "forbidden_hits": hits, "parent_traversal": traversal}


def _action_prompt(
    ir: dict[str, Any] | None, iteration: int, required_action: str | None,
    *, source_images_visible: bool = True,
) -> str:
    commitment = (
        f"\nYour previous verifier decision committed to this next action:\n{required_action}\n"
        "Implement that concrete action now, or implement a clearly stated correction if direct inspection proves "
        "it invalid. Do not return without changing candidate.py when an action is pending.\n"
        if required_action else ""
    )
    perception = (
        "Your structured perception record is in reconstruction-ir.json. Treat it as a hypothesis and\n"
        "correct it when the image evidence disagrees.\n\n"
        "Current reconstruction IR summary:\n"
        f"{json.dumps(ir, ensure_ascii=False)[:12000]}"
        if ir is not None else
        "No structured reconstruction record is provided. Infer the geometry directly from the source images."
    )
    source = (
        "Reconstruct the mechanical part shown in target.png as CadQuery code.\n"
        f"This is iteration {iteration}. The four source views are also view_0.png through view_3.png."
    )
    if not source_images_visible:
        source = (
            "Reconstruct the mechanical part described in reconstruction-ir.json as CadQuery code.\n"
            f"This is iteration {iteration}. An independent perception agent inspected the source images."
        )
        perception = (
            "Read the complete reconstruction-ir.json. Source images are withheld from this conversation "
            "and workspace. Treat the IR as a hypothesis; preserve its uncertainty and use verifier "
            "feedback to assess corrections. Do not search for source images or other agents' files.\n\n"
            f"Current reconstruction IR summary:\n{json.dumps(ir, ensure_ascii=False)[:12000]}"
        )
    return f"""{source}
{perception}
Create or repair candidate.py; it must import
cadquery and assign the final solid to `result`. You may run `python run_candidate.py` and inspect
candidate.png. Do not access parent directories or the network. Work directly in the current
directory. Do not merely describe code: implement and test the candidate.
{commitment}
"""


def _decision_prompt(iteration: int, maximum: int, execution: dict[str, Any], verdict: dict[str, Any] | None) -> str:
    remaining = maximum - iteration
    return f"""The harness has independently executed your current candidate.
Execution result:
{json.dumps(execution, ensure_ascii=False)}

Image-only verifier result (it never uses GT geometry):
{json.dumps(verdict, ensure_ascii=False) if verdict else 'unavailable because execution/render failed'}

There are {remaining} iterations left before the safety ceiling. Decide whether the current
candidate is good enough to submit, or whether a concrete geometry/code change is likely to
improve it. `stop` submits the current candidate for the hidden official BenchCAD score.
`continue` must name the next change. Return only the structured decision object.
"""


def _records(data_dir: Path, maximum: int | None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (data_dir / "records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:maximum] if maximum is not None else rows


def run_benchcad_campaign(config: BenchCADConfig) -> dict[str, Any]:
    if config.max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    if config.reconstruction_mode not in {"baseline", "forced_ir", "specialist_ir"}:
        raise ValueError("reconstruction_mode must be baseline, forced_ir, or specialist_ir")
    specialist = config.reconstruction_mode == "specialist_ir"
    upstream = config.upstream.resolve()
    data_dir = config.data_dir.resolve()
    python = upstream / ".venv/Scripts/python.exe"
    if not python.is_file():
        raise FileNotFoundError(f"Pinned BenchCAD Python not found: {python}")
    campaign_dir = (config.output / config.campaign).resolve()
    campaign_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for record in _records(data_dir, config.max_records):
        rid = record["record_id"]
        job = campaign_dir / rid
        workspace = job / "agent_workspace"
        attempts = job / "attempts"
        workspace.mkdir(parents=True, exist_ok=True)
        attempts.mkdir(parents=True, exist_ok=True)
        result_path = job / "result.json"
        if result_path.is_file():
            previous = json.loads(result_path.read_text(encoding="utf-8"))
            if previous.get("status") == "invalid_gt_access_audit":
                gt_forbidden = [
                    str((data_dir / record["step_path"]).resolve()),
                    str((data_dir / record["code_path"]).resolve()),
                ]
                audits = []
                for row in previous.get("trajectory", []):
                    turn_proxy = type("TurnProxy", (), {"provider_metadata": row["action_turn"]})()
                    row["audit"] = _audit_invocation(turn_proxy, gt_forbidden)
                    audits.append(row["audit"])
                if audits and all(audit["passed"] for audit in audits) and (job / "submitted.step").is_file():
                    previous["official"] = _run_bridge(python, [
                        "--upstream", str(upstream), "score", "--code", str(job / "submitted.py"),
                        "--step", str(job / "submitted.step"), "--gt-code", str(data_dir / record["code_path"]),
                        "--gt-step", str(data_dir / record["step_path"]), "--family", record["family"],
                        "--resolution", str(config.voxel_resolution),
                    ], config.exec_timeout + 300)
                    previous["status"] = "scored" if previous["official"].get("ok") else "score_failed"
                    previous["audit_replayed"] = True
                    result_path.write_text(json.dumps(previous, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            results.append(previous)
            continue
        target_source = data_dir / "steps" / f"{rid}.png"
        if not target_source.is_file():
            raise FileNotFoundError(f"Target render missing: {target_source}")
        source_workspace = job / "perception_workspace" if specialist else workspace
        source_workspace.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_source, source_workspace / "target.png")
        image = Image.open(target_source)
        width, height = image.size
        boxes = [(0, 0, width // 2, height // 2), (width // 2, 0, width, height // 2),
                 (0, height // 2, width // 2, height), (width // 2, height // 2, width, height)]
        for index, box in enumerate(boxes):
            image.crop(box).save(source_workspace / f"view_{index}.png")
        _write_run_helper(workspace, python, upstream, config.exec_timeout, (width - 12) // 2)
        provider = CodexCLIProvider(CodexCLIConfig(
            cwd=workspace, artifact_root=job / "model_events", model=config.model,
            reasoning_effort=config.effort, timeout_seconds=config.timeout,
        ))
        started = time.time()
        ir_value: dict[str, Any] | None = None
        handle: ConversationHandle | None = None
        if config.reconstruction_mode in {"forced_ir", "specialist_ir"}:
            builder = CodexCLIProvider(CodexCLIConfig(
                cwd=source_workspace, artifact_root=job / "perception_events", model=config.model,
                reasoning_effort=config.effort, timeout_seconds=config.timeout,
            )) if specialist else provider
            ir_result = build_reconstruction_ir(
                builder, sample_id=f"benchcad:{rid}", images=[source_workspace / "target.png"],
                output_dir=job / "ir_builder",
            )
            ir_value = ir_result.value
            (workspace / "reconstruction-ir.json").write_text(
                json.dumps(ir_value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            if not specialist:
                handle = ConversationHandle(
                    provider=provider.name, conversation_id=ir_result.conversation_id,
                )
        submitted = False
        trajectory: list[dict[str, Any]] = []
        required_action: str | None = None
        previous_candidate_sha256: str | None = None
        gt_forbidden = [str((data_dir / record["step_path"]).resolve()), str((data_dir / record["code_path"]).resolve())]
        model_forbidden = gt_forbidden + ([str(source_workspace.resolve()), str(target_source)] if specialist else [])
        leakage = False
        for iteration in range(1, config.max_iterations + 1):
            action_request = ModelRequest(
                instructions=_action_prompt(ir_value, iteration, required_action, source_images_visible=not specialist),
                images=[] if specialist else [workspace / "target.png"],
                metadata={"record_id": rid, "stage": "action", "iteration": iteration},
            )
            if handle is None:
                handle, action_turn = provider.start(action_request)
            else:
                handle, action_turn = provider.continue_(handle, action_request)
            audit = _audit_invocation(action_turn, model_forbidden)
            leakage = leakage or not audit["passed"]
            attempt = attempts / f"attempt-{iteration:03d}"
            attempt.mkdir()
            candidate = workspace / "candidate.py"
            if candidate.is_file():
                shutil.copy2(candidate, attempt / "candidate.py")
            candidate_sha256 = _sha256(candidate) if candidate.is_file() else None
            execution = {"ok": False, "stage": "missing_candidate", "errors": ["candidate.py was not created"]}
            verdict = None
            if candidate.is_file() and audit["passed"]:
                execution = _run_bridge(python, [
                    "--upstream", str(upstream), "execute", "--code", str(candidate),
                    "--step", str(attempt / "candidate.step"), "--render", str(attempt / "candidate.png"),
                    "--timeout", str(config.exec_timeout), "--parallel-scale", "0.55",
                    "--view-size", str((width - 12) // 2),
                ], config.exec_timeout + 60)
                if execution.get("ok"):
                    verdict = image_verdict(
                        source_workspace / "target.png", attempt / "candidate.png", attempt / "overlay.png",
                    )
                    shutil.copy2(attempt / "candidate.png", workspace / "candidate.png")
                    if not specialist:
                        shutil.copy2(attempt / "overlay.png", workspace / "difference.png")
            execution["candidate_sha256"] = candidate_sha256
            execution["candidate_changed"] = (
                None if previous_candidate_sha256 is None
                else candidate_sha256 != previous_candidate_sha256
            )
            (attempt / "execution.json").write_text(json.dumps(execution, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if verdict:
                (attempt / "image-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
            decision_images = [path for path in (workspace / "target.png", attempt / "candidate.png", attempt / "overlay.png") if path.is_file()]
            if specialist:
                decision_images = []
            handle, decision_turn = provider.continue_(handle, ModelRequest(
                instructions=_decision_prompt(iteration, config.max_iterations, execution, verdict),
                images=decision_images, response_schema=DECISION_SCHEMA,
                metadata={"record_id": rid, "stage": "decision", "iteration": iteration},
            ))
            decision = decision_turn.structured_output or {
                "decision": "continue", "reason": "invalid structured decision",
                "next_action": "repair the candidate", "confidence": 0,
            }
            decision_audit = _audit_invocation(decision_turn, model_forbidden)
            if specialist:
                leakage = leakage or not decision_audit["passed"]
            row = {
                "iteration": iteration, "action_turn": action_turn.provider_metadata,
                "action_usage": action_turn.usage, "action_finish_reason": action_turn.finish_reason,
                "execution": execution, "image_verdict": verdict, "decision": decision,
                "decision_turn": decision_turn.provider_metadata, "audit": audit,
                "decision_usage": decision_turn.usage,
                "decision_finish_reason": decision_turn.finish_reason,
                "decision_audit": decision_audit,
            }
            trajectory.append(row)
            (attempt / "turn.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if decision.get("decision") == "stop" and execution.get("ok") and audit["passed"]:
                submitted = True
                shutil.copy2(attempt / "candidate.py", job / "submitted.py")
                shutil.copy2(attempt / "candidate.step", job / "submitted.step")
                shutil.copy2(attempt / "candidate.png", job / "submitted.png")
                break
            required_action = str(decision.get("next_action") or "").strip() or None
            previous_candidate_sha256 = candidate_sha256
        official = None
        status = "no_submission"
        if submitted and not leakage:
            official = _run_bridge(python, [
                "--upstream", str(upstream), "score", "--code", str(job / "submitted.py"),
                "--step", str(job / "submitted.step"), "--gt-code", str(data_dir / record["code_path"]),
                "--gt-step", str(data_dir / record["step_path"]), "--family", record["family"],
                "--resolution", str(config.voxel_resolution),
            ], config.exec_timeout + 300)
            status = "scored" if official.get("ok") else "score_failed"
        elif leakage:
            status = "invalid_information_access_audit" if specialist else "invalid_gt_access_audit"
        payload = {
            "protocol": "evocad-benchcad-agent-v2", "record_id": rid, "family": record["family"],
            "difficulty": record.get("difficulty"), "variant": record.get("variant"),
            "model": config.model, "reasoning_effort": config.effort, "status": status,
            "reconstruction_mode": config.reconstruction_mode,
            "source_image_visibility": "builder_only" if specialist else "modeling_agent",
            "modeling_conversation_id": handle.conversation_id if handle else None,
            "submitted": submitted, "iterations": len(trajectory), "official": official,
            "elapsed_seconds": round(time.time() - started, 3), "trajectory": trajectory,
        }
        result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append(payload)
    scored = [row for row in results if (row.get("official") or {}).get("ok")]
    summary = {
        "protocol": "evocad-benchcad-campaign-v2", "campaign": config.campaign,
        "condition": "local-audited-process-pilot", "official_container_equivalent": False,
        "candidate_renderer": {"parallel_scale": 0.55, "view_size": "derived-from-target", "target_aligned": True},
        "model": config.model, "reconstruction_mode": config.reconstruction_mode,
        "records": len(results), "scored": len(scored),
        "mean_iou": round(sum(row["official"]["iou"] for row in scored) / len(scored), 6) if scored else 0.0,
        "mean_composite": round(sum(row["official"]["composite"] for row in scored) / len(scored), 6) if scored else 0.0,
        "config": {**asdict(config), "upstream": str(upstream), "data_dir": str(data_dir), "output": str(config.output.resolve())},
        "bridge_sha256": _sha256(project_root() / "evals/benchcad/official_bridge.py"),
        "data_selection_sha256": _sha256(data_dir / "selection.json") if (data_dir / "selection.json").is_file() else None,
        "results": [{key: row.get(key) for key in (
            "record_id", "family", "difficulty", "status", "reconstruction_mode",
            "iterations", "official",
        )} for row in results],
    }
    (campaign_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return summary
