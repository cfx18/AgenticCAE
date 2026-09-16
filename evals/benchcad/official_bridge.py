"""Small process boundary around BenchCAD's pinned official implementation."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import sys


ALLOWED_IMPORTS = {"cadquery", "math"}
FORBIDDEN_CALLS = {"compile", "eval", "exec", "globals", "input", "locals", "open", "__import__"}


def validate_candidate(code: str) -> list[str]:
    """Reject host-access primitives before locally executing model-authored code.

    This is defense in depth for the non-Docker pilot, not a security sandbox.
    The official agentic harness should be used when Docker is available.
    """
    errors: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error at line {exc.lineno}: {exc.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in ALLOWED_IMPORTS:
                    errors.append(f"import is not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".", 1)[0] not in ALLOWED_IMPORTS:
                errors.append(f"import is not allowed: {module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                errors.append(f"call is not allowed: {node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"dunder attribute is not allowed: {node.attr}")
    if not any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "result"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        for node in ast.walk(tree)
    ):
        errors.append("candidate must assign the final solid to `result`")
    return sorted(set(errors))


def _load_upstream(upstream: Path) -> None:
    sys.path.insert(0, str(upstream.resolve()))
    sys.path.insert(0, str((upstream / "Vision2Code").resolve()))
    os.environ.setdefault("PYTHONUTF8", "1")


def _patch_windows_exec_environment(exec_cq: object) -> None:
    if os.name != "nt":
        return
    safe_names = (
        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT",
        "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP", "PYTHONUTF8",
    )
    exec_cq.minimal_env = lambda: {  # type: ignore[attr-defined]
        key: value for key, value in os.environ.items() if key.upper() in safe_names
    }


def execute(args: argparse.Namespace) -> dict:
    code = args.code.read_text(encoding="utf-8", errors="replace")
    errors = [] if args.trusted_source else validate_candidate(code)
    if errors:
        return {"ok": False, "stage": "policy", "errors": errors}
    _load_upstream(args.upstream)
    from benchcad_core.scoring import exec_cq
    from benchcad_core.scoring import views

    _patch_windows_exec_environment(exec_cq)

    try:
        exec_cq.execute_cq_to_step(code, args.step, timeout=args.timeout)
        # This is the corpus-pinned setting used by BenchCAD's agentic Sandbox.
        # The module default moved to 0.90 after the stored target set was built.
        views.PARALLEL_SCALE = args.parallel_scale
        views.composite_for_step(args.step, args.render, size=args.view_size)
    except Exception as exc:  # BenchCAD converts execution failures into zero scores.
        return {
            "ok": False,
            "stage": "execute_or_render",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    return {
        "ok": True,
        "stage": "rendered",
        "step": str(args.step.resolve()),
        "render": str(args.render.resolve()),
        "parallel_scale": args.parallel_scale,
        "view_size": args.view_size,
    }


def score(args: argparse.Namespace) -> dict:
    _load_upstream(args.upstream)
    from benchcad_core.scoring.iou import iou_step_vs_step
    from scoring.composite import composite_score

    code = args.code.read_text(encoding="utf-8", errors="replace")
    gt_code = args.gt_code.read_text(encoding="utf-8", errors="replace")
    raw_iou = iou_step_vs_step(args.step, args.gt_step, res=args.resolution)
    composite = composite_score(
        gt_step=args.gt_step,
        gen_step=args.step,
        gen_code=code,
        gt_code=gt_code,
        family=args.family,
    )
    return {
        "ok": True,
        "score_type": "benchcad-official",
        "voxel_resolution": args.resolution,
        "iou": round(float(raw_iou), 6),
        "composite": round(float(composite), 6),
    }


def validate_step(args: argparse.Namespace) -> dict:
    _load_upstream(args.upstream)
    from benchcad_core.scoring.iou import iou_step_vs_step

    self_iou = iou_step_vs_step(args.step, args.step, res=args.resolution)
    return {
        "ok": self_iou >= 0.999999,
        "score_type": "benchcad-official-self-iou",
        "voxel_resolution": args.resolution,
        "self_iou": round(float(self_iou), 6),
        "stage": "validated" if self_iou >= 0.999999 else "invalid_gt_step",
    }


def render_step(args: argparse.Namespace) -> dict:
    _load_upstream(args.upstream)
    from benchcad_core.scoring import views

    views.PARALLEL_SCALE = args.parallel_scale
    if args.render.exists():
        args.render.unlink()
    views.composite_for_step(args.step, args.render, size=args.view_size)
    return {
        "ok": True, "stage": "rendered", "render": str(args.render.resolve()),
        "parallel_scale": args.parallel_scale, "view_size": args.view_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("execute")
    run.add_argument("--code", type=Path, required=True)
    run.add_argument("--step", type=Path, required=True)
    run.add_argument("--render", type=Path, required=True)
    run.add_argument("--timeout", type=int, default=600)
    run.add_argument("--parallel-scale", type=float, default=0.55)
    run.add_argument("--view-size", type=int, default=256)
    run.add_argument("--trusted-source", action="store_true")
    grade = sub.add_parser("score")
    grade.add_argument("--code", type=Path, required=True)
    grade.add_argument("--step", type=Path, required=True)
    grade.add_argument("--gt-code", type=Path, required=True)
    grade.add_argument("--gt-step", type=Path, required=True)
    grade.add_argument("--family", required=True)
    grade.add_argument("--resolution", type=int, default=64)
    validate = sub.add_parser("validate-step")
    validate.add_argument("--step", type=Path, required=True)
    validate.add_argument("--resolution", type=int, default=64)
    render = sub.add_parser("render")
    render.add_argument("--step", type=Path, required=True)
    render.add_argument("--render", type=Path, required=True)
    render.add_argument("--parallel-scale", type=float, default=0.55)
    render.add_argument("--view-size", type=int, default=256)
    args = parser.parse_args()
    try:
        if args.action == "execute":
            result = execute(args)
        elif args.action == "score":
            result = score(args)
        elif args.action == "validate-step":
            result = validate_step(args)
        else:
            result = render_step(args)
    except Exception as exc:
        result = {"ok": False, "stage": args.action, "errors": [f"{type(exc).__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
