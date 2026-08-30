from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).parents[1] / "verify.py"
sys.path.insert(0, str(MODULE_PATH.parent))
from cad_evoloop.verification import extract_autocad as EXTRACTOR
from cad_evoloop.verification import extract_core_console as CORE_EXTRACTOR
from cad_evoloop.verification import render_core_console as CORE_RENDERER


from cad_evoloop.verification import verify as VERIFY


def base_scene() -> dict:
    return {
        "active_command": "",
        "layers": [{"Name": "0"}, {"Name": "DIM"}],
        "layouts": [{"name": "Model", "model_type": True, "entity_count": 3}],
        "entities": [
            {"type": "AcDbCircle", "Radius": 5.0},
            {"type": "AcDbAlignedDimension", "Measurement": 10.0},
            {"type": "AcDbText", "TextString": "SECTION -AA"},
        ],
        "summary": {
            "entity_count": 3,
            "extraction_errors": 0,
            "type_counts": {"AcDbCircle": 1, "AcDbAlignedDimension": 1, "AcDbText": 1},
        },
    }


def test_core_extractor_keeps_process_cwd_outside_disposable_directory(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate.dwg"
    candidate.write_bytes(b"dwg")
    observed = {}

    def fake_run(command, **kwargs):
        observed["cwd"] = kwargs["cwd"]
        script = Path(command[command.index("/s") + 1])
        (script.parent / "scene.tsv").write_text("INSUNITS\t4\nDONE\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(CORE_EXTRACTOR.subprocess, "run", fake_run)

    scene = CORE_EXTRACTOR.extract_dwg_core(candidate)

    assert observed["cwd"] == candidate.parent
    assert scene["insunits"] == 4


def test_core_extractor_preserves_console_diagnostic_on_failure(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate.dwg"
    candidate.write_bytes(b"dwg")
    monkeypatch.setattr(
        CORE_EXTRACTOR.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=b"AutoLISP error", stderr=b"bad extractor",
        ),
    )

    with pytest.raises(RuntimeError, match=r"(?s)AutoLISP error.*bad extractor"):
        CORE_EXTRACTOR.extract_dwg_core(candidate)


def test_core_extractor_reads_dimension_measurement_from_dxf_group_42(tmp_path) -> None:
    lisp = CORE_EXTRACTOR.extractor_lisp(tmp_path / "scene.tsv")

    assert '(assoc 42 mcp-d)' in lisp
    assert "vla-get-Measurement" not in lisp


def test_core_renderer_uses_noninteractive_native_png_export(tmp_path) -> None:
    lisp = CORE_RENDERER.render_lisp(tmp_path / "candidate.png", tmp_path / "done")

    assert '(setvar "FILEDIA" 0)' in lisp
    assert '"_.PNGOUT"' in lisp
    assert '(ssget "_X" \'((410 . "Model")))' in lisp
    assert '"_.VPOINT" "1,-1,1"' in lisp


def test_core_renderer_requires_output_sentinel(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate.dwg"
    candidate.write_bytes(b"dwg")
    monkeypatch.setattr(
        CORE_RENDERER.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        CORE_RENDERER.render_dwg_core(candidate, tmp_path / "candidate.png")


def test_core_extractor_collects_layouts_dimstyles_and_entity_extents(tmp_path) -> None:
    lisp = CORE_EXTRACTOR.extractor_lisp(tmp_path / "scene.tsv")

    assert '(ssget "_X")' in lisp
    assert "vla-getboundingbox" in lisp
    assert '"LAYOUT\tModel\t1"' in lisp
    assert '"DIMSTYLE\t"' in lisp
    assert '"ENT2\t"' in lisp


def test_dimension_and_label_pass() -> None:
    task = {"dimensions": [{"id": "D1", "element": "hole", "measurement": "10 millimeter"}]}
    rubrics = {"rubrics": [{"id": "R1", "requirement": 'Include a circle labeled "SECTION -AA" with dimensions.'}]}
    verdict = VERIFY.verify_scene(task, rubrics, base_scene())
    assert verdict["passed"] is True
    assert verdict["dimensions"][0]["status"] == "pass"
    assert verdict["rubrics"][0]["status"] == "pass"


def test_missing_dimension_fails() -> None:
    scene = base_scene()
    scene["entities"] = [scene["entities"][0]]
    scene["summary"]["type_counts"] = {"AcDbCircle": 1}
    task = {"dimensions": [{"id": "D1", "measurement": "20 millimeter"}]}
    verdict = VERIFY.verify_scene(task, {"rubrics": []}, scene)
    assert verdict["passed"] is False
    assert verdict["dimensions"][0]["status"] == "fail"


def test_unverifiable_rubric_is_explicit() -> None:
    rubric = "The composition shall be visually balanced and suitable for manufacture."
    status, evidence = VERIFY.evaluate_rubric(rubric, base_scene())
    assert status == "unverified"
    assert evidence == []


def test_verified_rubric_failure_blocks_pass() -> None:
    task = {"dimensions": []}
    rubrics = {"rubrics": [{"id": "R1", "requirement": "The drawing shall include ANSI31 hatch."}]}
    verdict = VERIFY.verify_scene(task, rubrics, base_scene())
    assert verdict["rubrics"][0]["status"] == "fail"
    assert verdict["passed"] is False


def test_layer_zero_rubric_checks_entity_layer_not_layer_count() -> None:
    scene = {
        "layers": [{"Name": "0"}],
        "entities": [{"type": "AcDb3dSolid", "owner": "Model", "Layer": "0"}],
        "summary": {"type_counts": {"AcDb3dSolid": 1}},
    }
    status, evidence = VERIFY.evaluate_rubric(
        "The single 3D solid shall reside on layer 0 in Model space.", scene,
    )
    assert status == "pass"
    assert evidence == ["3D solids: 1", "model entities off Layer 0: []"]


def test_dimension_style_and_hidden_layers_require_native_evidence() -> None:
    scene = base_scene()
    scene["entities"][1]["DimStyle"] = "ISO-25"
    scene["layers"] = [
        {"Name": "OUTLINE", "Linetype": "Continuous"},
        {"Name": "HIDDEN", "Linetype": "HIDDEN2"},
    ]

    dimension_status, dimension_evidence = VERIFY.evaluate_rubric(
        "Dimensions shall use the ISO-25 dimension style.", scene,
    )
    layer_status, layer_evidence = VERIFY.evaluate_rubric(
        "Visible and hidden edges shall use dedicated continuous and hidden-line layers.", scene,
    )

    assert dimension_status == "pass"
    assert "ISO-25 dimension handles" in dimension_evidence[1]
    assert layer_status == "pass"
    assert any("hidden-line layers" in item for item in layer_evidence)


def test_layout1_rubric_rejects_empty_or_differently_named_paper_space() -> None:
    scene = base_scene()
    scene["layouts"] = [
        {"name": "Model", "model_type": True, "entity_count": 3},
        {"name": "Sheet", "model_type": False, "entity_count": 2},
    ]

    status, evidence = VERIFY.evaluate_rubric(
        "Layout1 shall present the projection views.", scene,
    )

    assert status == "fail"
    assert evidence[-1] == "nonempty Layout1 entries: 0"


def test_core_console_scene_parser_normalizes_geometry(tmp_path: Path) -> None:
    scene = CORE_EXTRACTOR.parse_scene([
        "INSUNITS\t4",
        "LAYER\tOBJECT",
        "LAYER\tHIDDEN\tHIDDEN2",
        "ENT\tCIRCLE\tOBJECT\t1A\t1,2,0\t5",
        "ENT\tLINE\tOBJECT\t1B\t-1,0,0\t3,4,0",
        "ENT\tTEXT\tDIM\t1C\t0,8,0\t2.5\tR10.0",
    ], tmp_path / "candidate.dwg")

    assert scene["insunits"] == 4
    assert scene["layers"][1] == {"Name": "HIDDEN", "Linetype": "HIDDEN2"}
    assert scene["summary"]["entity_count"] == 3
    assert scene["summary"]["type_counts"] == {
        "AcDbCircle": 1,
        "AcDbLine": 1,
        "AcDbText": 1,
    }
    assert scene["summary"]["bounds"] == {
        "min": [-4.0, -3.0, 0.0],
        "max": [6.0, 7.0, 0.0],
    }
    assert scene["entities"][2]["TextString"] == "R10.0"


def test_core_console_scene_parser_keeps_paper_space_and_solid_bbox(tmp_path: Path) -> None:
    scene = CORE_EXTRACTOR.parse_scene([
        "INSUNITS\t4",
        "LAYOUT\tModel\t1",
        "LAYOUT\tLayout1\t0",
        "DIMSTYLE\tISO-25",
        "ENT2\t3DSOLID\t0\t10\tModel\t0,0,0\t10,20,30",
        "ENT2\tDIMENSION\tDIM\t11\tLayout1\t1,2,0\t8,3,0\t42\tISO-25\t0",
    ], tmp_path / "candidate.dwg")

    assert scene["dimstyles"] == [{"Name": "ISO-25"}]
    assert scene["layouts"] == [
        {"name": "Model", "model_type": True, "entity_count": 1},
        {"name": "Layout1", "model_type": False, "entity_count": 1},
    ]
    assert scene["entities"][0]["bbox"] == {
        "min": [0.0, 0.0, 0.0], "max": [10.0, 20.0, 30.0],
    }
    assert scene["entities"][1]["owner"] == "Layout1"
    assert scene["entities"][1]["DimStyle"] == "ISO-25"
    assert scene["summary"]["bounds"] == {
        "min": [0.0, 0.0, 0.0], "max": [10.0, 20.0, 30.0],
    }


def test_collection_records_uses_dynamic_entity_dispatch(monkeypatch) -> None:
    raw_entity = type("RawEntity", (), {"_oleobj_": object()})()
    dynamic_entity = object()
    collection = type(
        "Collection",
        (),
        {"Count": 1, "Item": lambda self, index: raw_entity},
    )()

    dynamic = type(
        "Dynamic",
        (),
        {"DumbDispatch": staticmethod(lambda ole_object: dynamic_entity)},
    )()
    client = type("Client", (), {"dynamic": dynamic})()
    monkeypatch.setattr(EXTRACTOR, "_com_modules", lambda: (None, None, client))
    monkeypatch.setattr(
        EXTRACTOR,
        "extract_entity",
        lambda entity, owner: {"entity": entity, "owner": owner},
    )

    records = EXTRACTOR.collection_records(collection, "Model")
    assert records == [{"entity": dynamic_entity, "owner": "Model"}]
