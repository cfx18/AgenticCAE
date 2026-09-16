"""Build a ready-to-use multi-family CAD post-training seed batch.

This builder intentionally uses verified local BRep sources and deterministic
parametric fixtures. Public web/CAD listings are excluded until downloaded,
matched, and verified. Every task is sealed as an EvoCAD posttrain bundle and
the trusted reference output is graded once at build time.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable

import cadquery as cq
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.posttrain.bundle import seal_bundle
from cad_evoloop.posttrain.geometry import VIEWS, draw_view, extents, load_shape, normalized
from cad_evoloop.posttrain.verifier import grade_files


FAMILY_TARGETS = {
    "drawing_qa": 20,
    "ortho_to_cad": 20,
    "cad_repair_edit": 20,
    "text_image_to_cad_program": 20,
    "cad_software_operation": 20,
    "assembly": 20,
}


def workspace_path(path: Path, *, fresh: bool = False) -> Path:
    value = path.resolve()
    if value == ROOT or not value.is_relative_to(ROOT):
        raise ValueError("Output must stay inside the workspace")
    if fresh and value.exists():
        raise FileExistsError("Use a fresh output directory")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, value)


def export_shape(shape, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path))
    return load_shape(path)


def new_task(root: Path, task_id: str) -> Path:
    task = root / "tasks" / task_id
    for section in ("public", "private", "reference", "tests", "provenance"):
        (task / section).mkdir(parents=True, exist_ok=False)
    return task


def dimension_sheet(path: Path, title: str, lines: list[str]) -> None:
    image = Image.new("RGB", (980, 120 + 42 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 22), title, fill=(20, 28, 36))
    for index, line in enumerate(lines):
        draw.text((24, 82 + 42 * index), line, fill=(20, 20, 20))
    image.save(path)


def box_shape(x: float, y: float, z: float):
    return cq.Workplane("XY").box(x, y, z, centered=False).val()


def ring_shape(outer: float, inner: float, height: float):
    return cq.Solid.makeCylinder(outer / 2, height, (outer / 2, outer / 2, 0)).cut(
        cq.Solid.makeCylinder(inner / 2, height, (outer / 2, outer / 2, 0))
    ).clean()


def bracket_shape(width: float, depth: float, height: float, bore: float):
    base = box_shape(width, depth, height * 0.35)
    tower = cq.Workplane("XY").box(width * 0.42, depth, height, centered=False).val().translate(
        (width * 0.29, 0, 0)
    )
    hole = cq.Solid.makeCylinder(bore / 2, depth * 1.2, (width / 2, -depth * 0.1, height * 0.64), (0, 1, 0))
    return base.fuse(tower).cut(hole).clean()


def stepped_shaft(length: float, r1: float, r2: float):
    first = cq.Solid.makeCylinder(r1, length * 0.56, (r2, r2, 0), (1, 0, 0))
    second = cq.Solid.makeCylinder(r2, length * 0.44, (r2 + length * 0.56, r2, 0), (1, 0, 0))
    return first.fuse(second).clean()


def fixture(index: int):
    mode = index % 4
    if mode == 0:
        x, y, z = 24 + index, 18 + index % 7, 8 + index % 5
        return "box", box_shape(x, y, z), {"x": x, "y": y, "z": z}
    if mode == 1:
        outer, inner, height = 32 + index % 9, 10 + index % 5, 6 + index % 4
        return "ring", ring_shape(outer, inner, height), {"outer": outer, "inner": inner, "height": height}
    if mode == 2:
        width, depth, height, bore = 28 + index % 8, 14 + index % 5, 22 + index % 7, 6 + index % 4
        return "bracket", bracket_shape(width, depth, height, bore), {
            "width": width, "depth": depth, "height": height, "bore": bore}
    length, r1, r2 = 34 + index, 4 + index % 3, 7 + index % 4
    return "stepped_shaft", stepped_shaft(length, r1, r2), {"length": length, "r1": r1, "r2": r2}


def write_fixed_brep_task(task: Path, *, query: str, shape, task_type: str, ancestry: str,
                          public_extra: dict | None = None, reference_code: str | None = None) -> dict:
    target = export_shape(shape, task / "private/target.step")
    for view in VIEWS:
        draw_view(target, task / f"public/{view}.png", view=view)
    public = {
        "task_id": task.name,
        "query": query,
        "input_images": [f"{name}.png" for name in VIEWS],
        "answer_file": "model.step",
        "coordinate_convention": "Fixed right-handed XYZ in millimetres; do not translate, mirror, or auto-align."
    }
    if public_extra:
        public.update(public_extra)
    write(task / "public/task.json", public)
    write(task / "private/verifier.json", {
        "kind": "fixed_frame_brep",
        "target": "private/target.step",
        "volume_tolerance_mm3": 1e-3,
        "length_tolerance_mm": 1e-4,
        "alignment": "none"
    })
    write(task / "reference/answer.json", {"artifact": "model.step"})
    if reference_code:
        (task / "reference/solution.py").write_text(reference_code, encoding="utf-8")
    else:
        shutil.copyfile(task / "private/target.step", task / "reference/model.step")
    x, y, z = extents(target)
    write(task / "provenance/source.json", {
        "source": "deterministic_parametric_fixture",
        "ancestry": ancestry,
        "created_at": utc_now(),
        "extents_mm": [x, y, z],
        "target_sha256": sha256_file(task / "private/target.step"),
        "gt_status": "verified_gt"
    })
    seal_bundle(task, {"task_id": task.name, "task_type": task_type, "ancestry": ancestry,
                       "license": "project-generated-noncommercial-research",
                       "split": "multifamily_seed_v1", "gt_status": "verified_gt"})
    return grade_files(task, model=task / "reference/model.step" if (task / "reference/model.step").exists()
                       else task / "private/target.step")


def build_drawing_qa(output: Path, fusion_parts: list[Path], count: int) -> list[dict]:
    rows = []
    roles = ["visible_edge", "hidden_edge", "dimension_line", "extension_line"]
    part_index = 0
    while len(rows) < count and part_index < len(fusion_parts) * 4:
        source = fusion_parts[part_index % len(fusion_parts)]
        role = roles[part_index % len(roles)]
        task_id = f"drawing-qa-{len(rows)+1:03d}"
        task = new_task(output, task_id)
        try:
            source_shape, translation = normalized(load_shape(source))
            image_evidence = draw_view(source_shape, task / "public/drawing.png", view="front", marker_role=role)
        except Exception:
            shutil.rmtree(task)
            part_index += 1
            continue
        answer = {"role": role, "physical_boundary": role in {"visible_edge", "hidden_edge"}}
        write(task / "public/task.json", {
            "task_id": task_id,
            "query": "Classify the stroke at red marker A. Is it a physical projected boundary or a drafting annotation?",
            "input_images": ["drawing.png"],
            "answer_format": {"role": ["visible_edge", "hidden_edge", "dimension_line", "extension_line"],
                              "physical_boundary": "boolean"},
            "answer_file": "answer.json"
        })
        write(task / "private/verifier.json", {"kind": "json_fields", "expected": answer, "absolute_tolerance": 0})
        write(task / "reference/answer.json", answer)
        write(task / "private/drawing-lineage.json", image_evidence)
        write(task / "provenance/source.json", {
            "source": "Fusion360Gallery reconstruction source part",
            "source_step": source.name,
            "source_step_sha256": sha256_file(source),
            "translation_mm": translation,
            "gt_status": "verified_gt"
        })
        seal_bundle(task, {"task_id": task_id, "task_type": "drawing_qa", "ancestry": f"fusion360:{source.stem}",
                           "license": "Fusion360Gallery-custom-noncommercial",
                           "split": "multifamily_seed_v1", "gt_status": "verified_gt"})
        rows.append({"task_id": task_id, "family": "drawing_qa",
                     "reference_verdict": grade_files(task, answer=task / "reference/answer.json")})
        part_index += 1
    return rows


def build_ortho(output: Path, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        name, shape, params = fixture(index)
        task = new_task(output, f"ortho-cad-{index+1:03d}")
        lines = [f"Fixture: {name}", "Reconstruct all shown dimensions in mm.",
                 json.dumps(params, sort_keys=True)]
        dimension_sheet(task / "public/specification.png", "Dimension specification", lines)
        verdict = write_fixed_brep_task(task,
            query="Build the part from the three orthographic views and the dimension specification. Submit model.step.",
            shape=shape, task_type="orthographic_to_brep", ancestry=f"parametric:{name}:{index}",
            public_extra={"input_images": ["front.png", "top.png", "right.png", "specification.png"]})
        rows.append({"task_id": task.name, "family": "orthographic_to_brep", "reference_verdict": verdict})
    return rows


def build_repair(output: Path, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        _, target, params = fixture(index + 20)
        task = new_task(output, f"repair-edit-{index+1:03d}")
        box = target.BoundingBox()
        cutter = cq.Workplane("XY").box(max(box.xlen * .22, 1), box.ylen * 1.4, box.zlen * 1.4,
                                        centered=False).val().translate((box.xmin, box.ymin - box.ylen * .2, box.zmin - box.zlen * .2))
        initial = target.cut(cutter).clean()
        export_shape(initial, task / "public/initial.step")
        dimension_sheet(task / "public/edit-request.png", "CAD repair request", [
            "Restore the missing material on the low-X side.",
            "Preserve all other faces, cavities, and overall frame.",
            "Submit the corrected STEP in the original coordinate frame."
        ])
        verdict = write_fixed_brep_task(task,
            query="Repair initial.step according to the drawing/specification. Submit model.step.",
            shape=target, task_type="cad_repair_edit", ancestry=f"repair_fixture:{index}",
            public_extra={"input_images": ["front.png", "top.png", "right.png", "edit-request.png"],
                          "initial_model": "initial.step", "parameters": params})
        rows.append({"task_id": task.name, "family": "cad_repair_edit", "reference_verdict": verdict})
    return rows


def cadquery_code(name: str, params: dict) -> str:
    if name == "box":
        return (
            "import cadquery as cq\n"
            f"shape = cq.Workplane('XY').box({params['x']}, {params['y']}, {params['z']}, centered=False).val()\n"
            "cq.exporters.export(shape, 'model.step')\n"
        )
    if name == "ring":
        return (
            "import cadquery as cq\n"
            f"shape = cq.Solid.makeCylinder({params['outer']/2}, {params['height']}, ({params['outer']/2}, {params['outer']/2}, 0))\n"
            f"shape = shape.cut(cq.Solid.makeCylinder({params['inner']/2}, {params['height']}, ({params['outer']/2}, {params['outer']/2}, 0))).clean()\n"
            "cq.exporters.export(shape, 'model.step')\n"
        )
    if name == "bracket":
        return (
            "import cadquery as cq\n"
            f"base = cq.Workplane('XY').box({params['width']}, {params['depth']}, {params['height']*0.35}, centered=False).val()\n"
            f"tower = cq.Workplane('XY').box({params['width']*0.42}, {params['depth']}, {params['height']}, centered=False).val().translate(({params['width']*0.29}, 0, 0))\n"
            f"hole = cq.Solid.makeCylinder({params['bore']/2}, {params['depth']*1.2}, ({params['width']/2}, {-params['depth']*0.1}, {params['height']*0.64}), (0, 1, 0))\n"
            "shape = base.fuse(tower).cut(hole).clean()\n"
            "cq.exporters.export(shape, 'model.step')\n"
        )
    return (
        "import cadquery as cq\n"
        f"shape = cq.Solid.makeCylinder({params['r1']}, {params['length']*0.56}, ({params['r2']}, {params['r2']}, 0), (1, 0, 0))\n"
        f"shape = shape.fuse(cq.Solid.makeCylinder({params['r2']}, {params['length']*0.44}, ({params['r2'] + params['length']*0.56}, {params['r2']}, 0), (1, 0, 0))).clean()\n"
        "cq.exporters.export(shape, 'model.step')\n"
    )


def build_text_program(output: Path, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        name, shape, params = fixture(index + 60)
        task = new_task(output, f"text-cadquery-{index+1:03d}")
        query = f"Write a CadQuery program that creates this {name} with parameters {json.dumps(params, sort_keys=True)}. Export model.step."
        code = cadquery_code(name, params)
        (task / "reference/solution.py").write_text(code, encoding="utf-8")
        subprocess.run([sys.executable, "solution.py"], cwd=task / "reference", check=True, timeout=90)
        verdict = write_fixed_brep_task(task, query=query, shape=shape, task_type="text_image_to_cad_program",
                                        ancestry=f"cadquery_fixture:{name}:{index}", reference_code=code)
        rows.append({"task_id": task.name, "family": "text_image_to_cad_program", "reference_verdict": verdict})
    return rows


def build_cad_ops(output: Path, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        name, shape, params = fixture(index + 100)
        task = new_task(output, f"cad-op-{index+1:03d}")
        actions = [{"op": "create_fixture", "fixture": name, "parameters_mm": params},
                   {"op": "export_step", "path": "model.step"}]
        write(task / "reference/actions.json", {"backend": "cad_action_fixture_v1", "actions": actions})
        verdict = write_fixed_brep_task(task,
            query=("Use CAD software operations to create the requested artifact. "
                   f"Operation intent: {json.dumps(actions, sort_keys=True)}. Submit model.step."),
            shape=shape, task_type="cad_software_operation", ancestry=f"cad_action_fixture:{name}:{index}",
            public_extra={"operation_backend": "cad_action_fixture_v1",
                          "operation_request": actions})
        rows.append({"task_id": task.name, "family": "cad_software_operation", "reference_verdict": verdict})
    return rows


def build_assembly(output: Path, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        task = new_task(output, f"assembly-{index+1:03d}")
        base_x, base_y, base_z = 30 + index % 5, 18 + index % 4, 5
        post_r, post_h = 3 + index % 3, 14 + index % 6
        base = box_shape(base_x, base_y, base_z)
        left = cq.Solid.makeCylinder(post_r, post_h, (base_x * .25, base_y * .5, base_z))
        right = cq.Solid.makeCylinder(post_r, post_h, (base_x * .75, base_y * .5, base_z))
        bridge = box_shape(base_x * .7, post_r * 2, 4).translate((base_x * .15, base_y * .5 - post_r, base_z + post_h - 2))
        assembly_shape = base.fuse(left).fuse(right).fuse(bridge).clean()
        spec = {"components": [
            {"name": "base_plate", "shape": "box", "size_mm": [base_x, base_y, base_z], "origin_mm": [0, 0, 0]},
            {"name": "left_post", "shape": "cylinder", "radius_mm": post_r, "height_mm": post_h,
             "origin_mm": [base_x * .25, base_y * .5, base_z]},
            {"name": "right_post", "shape": "cylinder", "radius_mm": post_r, "height_mm": post_h,
             "origin_mm": [base_x * .75, base_y * .5, base_z]},
            {"name": "top_bridge", "shape": "box", "size_mm": [base_x * .7, post_r * 2, 4],
             "origin_mm": [base_x * .15, base_y * .5 - post_r, base_z + post_h - 2]}],
            "constraint": "posts are mounted on the base and connected by the bridge"}
        write(task / "reference/assembly.json", spec)
        dimension_sheet(task / "public/assembly-spec.png", "Assembly specification", [
            f"Base plate: {base_x} x {base_y} x {base_z} mm.",
            f"Two posts: radius {post_r} mm, height {post_h} mm.",
            "Posts are centered at 25% and 75% of base X and at mid-depth.",
            "Bridge touches both posts near the top."
        ])
        verdict = write_fixed_brep_task(task,
            query="Create the assembly from the component specification. Export the final assembled solid as model.step.",
            shape=assembly_shape, task_type="assembly", ancestry=f"assembly_fixture:{index}",
            public_extra={"input_images": ["front.png", "top.png", "right.png", "assembly-spec.png"],
                          "assembly_contract": "component graph recorded in reference/assembly.json"})
        rows.append({"task_id": task.name, "family": "assembly", "reference_verdict": verdict})
    return rows


BUILDERS: dict[str, Callable[..., list[dict]]] = {
    "drawing_qa": build_drawing_qa,
    "ortho_to_cad": build_ortho,
    "cad_repair_edit": build_repair,
    "text_image_to_cad_program": build_text_program,
    "cad_software_operation": build_cad_ops,
    "assembly": build_assembly,
}


def build_seed(output: Path, source_dir: Path, per_family: int) -> dict:
    output = workspace_path(output, fresh=True)
    source_dir = workspace_path(source_dir)
    output.mkdir(parents=True)
    fusion_parts = sorted(source_dir.glob("*.step"))
    if len(fusion_parts) < 8:
        raise ValueError("Need at least eight Fusion source parts for drawing QA diversity")
    rows: list[dict] = []
    rows.extend(build_drawing_qa(output, fusion_parts, per_family))
    for family in ("ortho_to_cad", "cad_repair_edit", "text_image_to_cad_program",
                   "cad_software_operation", "assembly"):
        rows.extend(BUILDERS[family](output, per_family))
    failures = [row for row in rows if not row["reference_verdict"].get("passed")]
    summary = {
        "dataset_id": output.name,
        "created_at": utc_now(),
        "task_count": len(rows),
        "family_counts": dict(Counter(row["family"] for row in rows)),
        "gt_status": "verified_gt_for_all_tasks",
        "reference_passed": sum(bool(row["reference_verdict"].get("passed")) for row in rows),
        "reference_failures": failures,
        "source_dir": str(source_dir.relative_to(ROOT)),
        "source_manifest_sha256": sha256_file(source_dir / "source-manifest.json") if (source_dir / "source-manifest.json").exists() else None,
        "notes": [
            "Ready-to-use posttrain bundles with public/private/reference/tests/provenance sections.",
            "The CAD software operation family uses deterministic CAD-action fixtures, not live AutoCAD/SolidWorks sessions.",
            "Assembly tasks include component-level reference JSON but are graded by final BRep until a multi-body verifier is added."
        ],
        "tasks": [{"task_id": row["task_id"], "family": row["family"],
                   "passed": row["reference_verdict"].get("passed")} for row in rows]
    }
    write(output / "dataset-summary.json", summary)
    if failures:
        raise RuntimeError(f"{len(failures)} reference tasks failed")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "evals/data/sources/fusion360gallery/posttrain-fusion-r1")
    parser.add_argument("--per-family", type=int, default=20)
    args = parser.parse_args()
    if not 5 <= args.per_family <= 30:
        parser.error("--per-family must be between 5 and 30")
    result = build_seed(args.output, args.source_dir, args.per_family)
    print(json.dumps({key: result[key] for key in ("task_count", "family_counts", "reference_passed")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
