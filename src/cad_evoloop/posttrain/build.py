"""Build a small source-grounded review pilot, not automatically accepted gold."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import cadquery as cq
from PIL import Image, ImageChops, ImageDraw

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from .bundle import contained_file, seal_bundle
from .environment import Episode
from .geometry import VIEWS, cylinders, draw_view, extents, font, load_shape, normalized, shape_verdict
from .verifier import grade_episode, grade_files


def write(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, value)


def export(shape, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path))
    return load_shape(path)


def dimension_sheet(path: Path, title: str, notes: list[str]):
    image = Image.new("RGB", (1100, 100 + 44 * len(notes)), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 20), title, fill="#18212b", font=font(26))
    for index, note in enumerate(notes):
        draw.text((24, 76 + index * 44), note, fill="#171717", font=font(22))
    image.save(path)


def geometry_cases(task: dict, shape):
    dimensions = extents(shape)
    mode = task["mode"]
    negatives = {}
    if mode in {"bore", "depth"}:
        eligible = [feature for feature in cylinders(shape) if feature["internal"] and abs(feature["angular_span"] - 2*math.pi) < 1e-5]
        if not eligible:
            raise ValueError("No verified internal, full-circle cylindrical face")
        feature = min(eligible, key=lambda f: f["radius_mm"])
        radius = feature["radius_mm"]
        direction = cq.Vector(*feature["axis"])
        start = cq.Vector(*feature["origin_mm"]) + direction * feature["v_min"]
        depth = feature["v_max"] - feature["v_min"]
        tool = cq.Solid.makeCylinder(radius, depth, start, direction)
        filled = shape.fuse(tool).clean()
        if mode == "bore":
            initial = filled.cut(cq.Solid.makeCylinder(radius * .8, depth, start, direction)).clean()
        else:
            initial = filled.cut(cq.Solid.makeCylinder(radius, depth*.6, start, direction)).clean()
        negatives["unrepaired"] = initial
        negatives["overbore"] = filled.cut(cq.Solid.makeCylinder(radius*1.08, depth, start, direction)).clean()
        negatives["short_depth"] = filled.cut(cq.Solid.makeCylinder(radius, depth*.7, start+direction*depth*.3, direction)).clean()
        code = (
            "import cadquery as cq\n"
            "shape = cq.importers.importStep('../input/initial.step').val()\n"
            f"tool = cq.Solid.makeCylinder({radius!r}, {depth!r}, cq.Vector{start.toTuple()!r}, cq.Vector{direction.toTuple()!r})\n"
            "shape = shape.cut(tool).clean()\n"
        )
        notes = [f"Cylindrical void diameter: {2*radius:.4f} mm", f"Axial span: {depth:.4f} mm",
                 f"Axis direction: {tuple(round(x,5) for x in direction.toTuple())}",
                 f"Start of void: {tuple(round(x,5) for x in start.toTuple())} mm",
                 "Preserve all other material and all external dimensions."]
        proof = {"source_cylindrical_face": feature, "initial_error": mode, "start_mm": start.toTuple(), "depth_mm": depth}
    elif mode in {"length", "box"}:
        x, y, z = dimensions
        reference = cq.Workplane("XY").box(x, y, z, centered=False).val()
        if not shape_verdict(reference, shape)["passed"]:
            raise ValueError("Source is not the independently reconstructed box")
        initial = cq.Workplane("XY").box(x, y*.8, z, centered=False).val()
        negatives["short_length"] = initial
        negatives["axes_swapped"] = cq.Workplane("XY").box(y, x, z, centered=False).val()
        code = f"import cadquery as cq\nshape = cq.Workplane('XY').box({x!r}, {y!r}, {z!r}, centered=False).val()\n"
        notes = ["Rectangular solid; no internal cavities.", f"X: {x:.4f} mm    Y: {y:.4f} mm    Z: {z:.4f} mm",
                 "Minimum X, Y and Z coordinates are all zero."]
        proof = {"independent_construction": "box", "analytic_volume_mm3": x*y*z}
    elif mode == "ring":
        # This fixture is tied to the audited upstream bearing ring, not guessed for arbitrary parts.
        reference = cq.Solid.makeCylinder(22.5, 6, (22.5,22.5,0)).fuse(
            cq.Solid.makeCylinder(17, 4, (22.5,22.5,6))).cut(
            cq.Solid.makeCylinder(12.5, 10, (22.5,22.5,0))).clean()
        if not shape_verdict(reference, shape)["passed"]:
            raise ValueError("Bearing ring reference does not match upstream BRep")
        initial = None
        negatives["missing_bore"] = cq.Solid.makeCylinder(22.5, 6, (22.5,22.5,0)).fuse(cq.Solid.makeCylinder(17, 4, (22.5,22.5,6)))
        negatives["blind_instead_of_through"] = negatives["missing_bore"].cut(cq.Solid.makeCylinder(12.5, 8, (22.5,22.5,2)))
        code = (
            "import cadquery as cq\n"
            "shape = cq.Solid.makeCylinder(22.5, 6, (22.5,22.5,0))\n"
            "shape = shape.fuse(cq.Solid.makeCylinder(17, 4, (22.5,22.5,6)))\n"
            "shape = shape.cut(cq.Solid.makeCylinder(12.5, 10, (22.5,22.5,0))).clean()\n"
        )
        notes = ["Concentric stepped ring; all axes parallel to Z.", "Lower stage: diameter 45 mm, Z = 0 to 6 mm.",
                 "Upper stage: diameter 34 mm, Z = 6 to 10 mm.", "Central through bore: diameter 25 mm.",
                 "Common axis: X = 22.5 mm, Y = 22.5 mm. No fillets or chamfers."]
        proof = {"independent_construction": "three_cylinders", "analytic_volume_mm3": 8265.530271594745}
    else:
        raise ValueError(f"Unknown geometric fixture: {mode}")
    # This catches collateral edits that volume-only verification can miss.
    negatives["translated"] = shape.translate((.5, 0, 0))
    negatives["collateral_cut"] = shape.cut(cq.Solid.makeBox(dimensions[0]*.2, dimensions[1], dimensions[2])).clean()
    code += "cq.exporters.export(shape, 'model.step')\n"
    return initial, code, negatives, notes, proof


def build_task(config: dict, source_dir: Path, output: Path, source_record: dict) -> dict:
    task = output / "tasks" / config["id"]
    task.mkdir(parents=True, exist_ok=False)
    for section in ("public", "private", "reference", "tests", "provenance"):
        (task / section).mkdir()
    source = source_dir / (config["part"] + ".step")
    original = load_shape(source)
    shape, translation = normalized(original)
    canonicalization = None
    if config["part"] == "100622_1c7038f5_0003":
        rebuilt = cq.Solid.makeCylinder(22.5, 6, (22.5,22.5,0)).fuse(
            cq.Solid.makeCylinder(17, 4, (22.5,22.5,6))).cut(
            cq.Solid.makeCylinder(12.5, 10, (22.5,22.5,0))).clean()
        canonicalization = shape_verdict(rebuilt, shape)
        if not canonicalization["passed"] or abs(shape.Volume()-8265.530271594745) > 1e-5:
            raise ValueError("Independent bearing ring construction does not match source")
        export(shape, task / "provenance/source-normalized.step")
        shape = rebuilt
    export(shape, task / "private/target.step")
    x, y, z = extents(shape)
    base = {"task_id": config["id"], "units": "mm", "input_images": [],
            "coordinate_convention": "Fixed right-handed XYZ; BRep bbox minimum translated to origin.",
            "answer_file": "answer.json"}
    evidence = {"source": source_record, "source_step_sha256": sha256_file(source), "translation_mm": translation,
                "shape_volume_mm3": shape.Volume(), "extents_mm": [x,y,z], "cylinders": cylinders(shape),
                "drawing_status": "generated from source CAD; not an original human engineering drawing",
                "independent_expert_review": "pending"}
    if canonicalization:
        evidence["canonicalization"] = {"reason": "OCCT boolean non-transitivity for source versus re-cut periodic faces",
                                         "method": "independent three-cylinder construction checked against source BRep and analytic volume",
                                         "equivalence_check": canonicalization}
    shutil.copyfile(source_dir / "LICENSE.upstream.md", task / "provenance/LICENSE.upstream.md")
    answer = {}
    image_evidence = {}
    negatives = {}
    kind = config["type"]
    if kind == "line_role":
        error = None
        for view in VIEWS:
            try:
                image_evidence["drawing.png"] = draw_view(shape, task / "public/drawing.png", view=view, marker_role=config["role"])
                error = None
                break
            except ValueError as exc:
                error = exc
        if error:
            raise error
        base["query"] = "Classify the stroke at the centre of red marker A. Ignore the red marker itself. Is the stroke a projected physical boundary, or a drafting annotation?"
        base["answer_format"] = {"role": ["visible_edge", "hidden_edge", "dimension_line", "extension_line"], "physical_boundary": "boolean"}
        answer = {"role": config["role"], "physical_boundary": config["role"] in {"visible_edge", "hidden_edge"}}
    elif kind == "dimension_attachment":
        image_evidence["drawing.png"] = draw_view(shape, task / "public/drawing.png", view="top" if config["mode"] == "bore" else "front", marker_role=None if config["mode"] == "bore" else "dimension_line")
        if config["mode"] == "bore":
            value = 2*min((c for c in cylinders(shape) if c["internal"]), key=lambda c: c["radius_mm"])["radius_mm"]
            dimension_sheet(task / "public/detail.png", "Detail A: central bore", [f"DIA {value:.3f} THRU", "The outer diameter is 45.000 mm."])
            base["query"] = "Read Detail A. Give the bore diameter in mm and whether it is through or blind; do not substitute the outer diameter."
            answer = {"feature": "central_bore", "diameter_mm": value, "extent": "through"}
        else:
            base["query"] = "What does the dimension marked A constrain? Give its value in mm and whether its stroke is itself a physical edge of the part."
            answer = {"feature": "overall_x_extent", "value_mm": x, "physical_boundary": False}
        base["answer_format"] = {key: "number" if isinstance(value, float) else "boolean" if isinstance(value, bool) else "string" for key,value in answer.items()}
        base["accepted_terms"] = ["central_bore", "through", "blind"] if config["mode"] == "bore" else ["overall_x_extent", "overall_y_extent", "overall_z_extent", "hole_diameter"]
    elif kind == "cross_view":
        for view in VIEWS:
            image_evidence[view + ".png"] = draw_view(shape, task / f"public/{view}.png", view=view)
        base["query"] = "Combine the three orthographic views into one XYZ bounding-size specification. Use the stated horizontal and vertical axes, not the screen position of a view. Report the three overall dimensions in mm."
        answer = {"x_mm": x, "y_mm": y, "z_mm": z}
        base["answer_format"] = {key: "number" for key in answer}
    elif kind == "clarification":
        axis = cylinders(shape)[0]["axis"]
        axis_index = max(range(3), key=lambda index: abs(axis[index]))
        view = {0:"right",1:"front",2:"top"}[axis_index]
        image_evidence["drawing.png"] = draw_view(shape, task / "public/drawing.png", view=view, dimensions=False, hidden=False)
        matrix = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        matrix[axis_index][axis_index] = 1.25
        alternative = shape.transformGeometry(cq.Matrix(matrix))
        export(alternative, task / "private/alternative.step")
        draw_view(alternative, task / "private/alternative.png", view=view, dimensions=False, hidden=False)
        with Image.open(task / "public/drawing.png") as a, Image.open(task / "private/alternative.png") as b:
            diff = ImageChops.difference(a,b).convert("L")
            mismatch = sum(value > 32 for value in diff.getdata()) / (diff.width*diff.height)
        if mismatch > .01 or abs(alternative.Volume()-shape.Volume()) < .1:
            raise ValueError("Ambiguity witness did not preserve projection or change geometry")
        evidence["ambiguity_witness"] = {"alternate_volume_mm3": alternative.Volume(), "projection_pixel_disagreement": mismatch,
                                          "changed_axis": "XYZ"[axis_index], "scale": 1.25}
        base["query"] = "You have only this end view, with hidden lines suppressed and no scale or dimensions. Can you uniquely determine the axial length? State the additional evidence needed before final modelling."
        base["answer_format"] = {"sufficient": "boolean", "missing_parameter": ["axial_length", "none"], "request": ["axial_dimension", "no_more_evidence"]}
        answer = {"sufficient": False, "missing_parameter": "axial_length", "request": "axial_dimension"}
    elif kind == "projection_diagnosis":
        image_evidence["reference.png"] = draw_view(shape, task / "public/reference.png", view="front", title="Required front view")
        actual_view = "right" if config["mode"] == "view_direction" else "front"
        image_evidence["current.png"] = draw_view(shape, task / "public/current.png", view=actual_view,
                                                   hidden_as_solid=config["mode"] == "hidden_line_style", title="Current export")
        export(shape, task / "public/current.step")
        base["query"] = "The attached STEP is the model used for both exports. Diagnose the export discrepancy before changing geometry. The required view is front (X horizontal, Z vertical)."
        base["answer_format"] = {"cause": ["hidden_line_style", "view_direction", "wrong_geometry"], "geometry_change_required": "boolean"}
        answer = {"cause": config["mode"], "geometry_change_required": False}
    elif kind in {"local_repair", "reconstruction"}:
        initial, code, negatives, notes, proof = geometry_cases(config, shape)
        evidence["reference_construction"] = proof
        for view in VIEWS:
            image_evidence[view + ".png"] = draw_view(shape, task / f"public/{view}.png", view=view)
        dimension_sheet(task / "public/specification.png", "Manufacturing dimensions (mm)", notes)
        (task / "reference/solution.py").write_text(code, encoding="utf-8")
        if kind == "local_repair":
            export(initial, task / "public/initial.step")
        base["query"] = ("Repair initial.step to satisfy the drawing and specification. Preserve all unspecified geometry. " if kind == "local_repair" else "Build the part from the three views and complete dimension specification. ") + "Submit one valid solid as model.step in the stated coordinate frame. You may use any modelling operations."
        base["answer_file"] = "model.step"
        answer = {"artifact": "model.step"}
    else:
        raise ValueError("Unsupported pilot task")
    base["input_images"] = [p.name for p in sorted((task / "public").glob("*.png"))]
    write(task / "public/task.json", base)
    write(task / "reference/answer.json", answer)
    write(task / "provenance/source.json", evidence)
    write(task / "private/drawing-lineage.json", image_evidence)
    if negatives:
        for name, negative in negatives.items():
            export(negative, task / f"tests/{name}.step")
        verifier = {"kind": "fixed_frame_brep", "target": "private/target.step", "volume_tolerance_mm3": 1e-3,
                    "length_tolerance_mm": 1e-4, "alignment": "none"}
    else:
        verifier = {"kind": "json_fields", "expected": answer, "absolute_tolerance": 1e-3}
        if kind == "line_role":
            wrong = {"role": "visible_edge" if answer["role"] != "visible_edge" else "hidden_edge", "physical_boundary": True}
        elif kind == "dimension_attachment":
            wrong = {**answer, "diameter_mm": 45.0} if "diameter_mm" in answer else {**answer, "physical_boundary": True}
        elif kind == "cross_view":
            wrong = {"x_mm": y, "y_mm": x, "z_mm": z}
        elif kind == "clarification":
            wrong = {"sufficient": True, "missing_parameter": "none", "request": "no_more_evidence"}
        elif kind == "projection_diagnosis":
            wrong = {"cause": "wrong_geometry", "geometry_change_required": True}
        write(task / "tests/wrong-answer.json", wrong)
        write(task / "tests/missing-answer.json", {})
    write(task / "private/verifier.json", verifier)
    seal_bundle(task, {"task_id": config["id"], "task_type": kind,
                       "ancestry": "fusion360:" + config["part"], "split_group": "fusion360:" + "_".join(config["part"].split("_")[:2]),
                       "license": "Fusion360Gallery-custom-noncommercial", "split": "review_pilot_unassigned",
                       "source_part_id": config["part"], "source_authenticity": "human-designed CAD; generated drawing and query"})
    return accept_task(task, output)


def accept_task(task: Path, output: Path) -> dict:
    """Mechanical acceptance only; this does not approve labels for training."""
    episode = Episode.reset(task, output / "episodes" / task.name / "reference-01")
    public = json.loads((task / "public/task.json").read_text())
    observation = episode.observe(public["input_images"][0], intent="Reference-run plumbing check: retain the exact input raster.")
    episode.conclude_observation(observation["observation_id"], "Reference fixture run, not a model inference or human annotation.")
    code = task / "reference/solution.py"
    if code.exists():
        program = episode.root / "work/reference.py"
        shutil.copyfile(code, program)
        result = subprocess.run([sys.executable, str(program)], cwd=episode.root / "work", capture_output=True, text=True, timeout=90, check=False)
        episode.record("trusted_reference_execution", {"argv": [sys.executable, "reference.py"], "exit_code": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr, "security": "trusted_fixture_only_not_agent_sandbox"})
        if result.returncode:
            raise RuntimeError(f"Reference failed for {task.name}: {result.stderr}")
        names = ["model.step"]
    else:
        shutil.copyfile(task / "reference/answer.json", episode.root / "work/answer.json")
        names = ["answer.json"]
    episode.submit(names)
    positive = grade_episode(task, episode)
    bad = []
    for path in sorted((task / "tests").glob("*")):
        verdict = grade_files(task, model=path if path.suffix == ".step" else None,
                              answer=path if path.suffix == ".json" else None)
        bad.append({"name": path.name, "verdict": verdict})
    replay = Episode.reset(task, output / "episodes" / task.name / "reset-check")
    repeated = replay.state["public_inventory"] == episode.state["public_inventory"]
    result = {"task_id": task.name, "reference_passed": positive["passed"], "negative_checks": bad,
              "reset_inventory_repeated": repeated, "mechanical_passed": positive["passed"] and repeated and all(not row["verdict"]["passed"] for row in bad),
              "human_review": "pending", "agent_model_executed": False,
              "reference_episode": episode.root.relative_to(output).as_posix()}
    write(output / "acceptance" / f"{task.name}.json", result)
    return result


def build_pilot(source_dir: Path, output: Path, selection: Path) -> dict:
    workspace = Path(__file__).resolve().parents[3]
    source_dir, output, selection = source_dir.resolve(), output.resolve(), selection.resolve()
    if not output.resolve().is_relative_to(workspace) or output.resolve() == workspace:
        raise ValueError("Pilot output must stay in the project")
    if output.exists():
        raise FileExistsError("Build a new immutable pilot version")
    manifest = json.loads((source_dir / "source-manifest.json").read_text())
    if sha256_file(contained_file(source_dir, "LICENSE.upstream.md")) != manifest.get("license_sha256"):
        raise ValueError("Source license identity changed or is missing")
    for part in manifest["parts"]:
        for file in part["files"]:
            if sha256_file(contained_file(source_dir, file["path"])) != file["sha256"]:
                raise ValueError("Source dataset content changed")
    records = {part["part_id"]: part for part in manifest["parts"]}
    config = json.loads(selection.read_text())
    output.mkdir(parents=True)
    write(output / "environment.json", {"python": sys.version, "executable": sys.executable,
          "packages": dict(sorted((distribution.metadata["Name"], distribution.version) for distribution in importlib.metadata.distributions())),
          "generator_files": [{"path": str(path.relative_to(workspace)), "sha256": sha256_file(path)}
                              for path in sorted(Path(__file__).parent.glob("*.py"))]})
    rows = []
    failures = []
    for task in config["tasks"]:
        try:
            row = build_task(task, source_dir, output, records[task["part"]])
            rows.append(row)
            print(f"{task['id']}: mechanical_passed={row['mechanical_passed']}", flush=True)
        except Exception as exc:
            failures.append({"task_id": task["id"], "error_type": type(exc).__name__, "message": str(exc)})
            print(f"{task['id']}: QUARANTINED {type(exc).__name__}: {exc}", flush=True)
    summary = {"pilot_id": config["pilot_id"], "source_manifest_sha256": sha256_file(source_dir / "source-manifest.json"),
               "selection_sha256": sha256_file(selection), "selected": len(config["tasks"]), "completed": len(rows),
               "mechanical_passed": sum(row["mechanical_passed"] for row in rows), "human_accepted": 0,
               "distinct_parts": len({task["part"] for task in config["tasks"]}),
               "type_counts": dict(Counter(task["type"] for task in config["tasks"])), "results": rows, "quarantined": failures,
               "security_status": "agent_execution_not_enabled; container integration untested",
               "limitations": ["Generated drawings, not original human drawings", "Pilot contains simple bounding-size cross-view tasks",
                               "No centreline, hatching or true section task yet", "No human labels accepted; no model training"]}
    write(output / "pilot-summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--selection", type=Path, default=Path("evals/posttrain/pilot.json"))
    args = parser.parse_args()
    result = build_pilot(args.source_dir, args.output, args.selection)
    print(json.dumps({key: result[key] for key in ("completed", "mechanical_passed", "human_accepted", "quarantined")}))
    raise SystemExit(0 if result["mechanical_passed"] == result["selected"] else 1)
