from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

MODULE_PATH = Path(__file__).parents[1] / "verify.py"
sys.path.insert(0, str(MODULE_PATH.parent))
import extract_autocad as EXTRACTOR
import extract_core_console as CORE_EXTRACTOR


SPEC = importlib.util.spec_from_file_location("cad_verifier", MODULE_PATH)
VERIFY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)


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
        (script.parent / "scene.tsv").write_text("INSUNITS\t4\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(CORE_EXTRACTOR.subprocess, "run", fake_run)

    scene = CORE_EXTRACTOR.extract_dwg_core(candidate)

    assert observed["cwd"] == candidate.parent
    assert scene["insunits"] == 4


def test_core_extractor_reads_dimension_measurement_from_dxf_group_42(tmp_path) -> None:
    lisp = CORE_EXTRACTOR.extractor_lisp(tmp_path / "scene.tsv")

    assert '(assoc 42 mcp-d)' in lisp
    assert "vla-get-Measurement" not in lisp


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


def test_core_console_scene_parser_normalizes_geometry(tmp_path: Path) -> None:
    scene = CORE_EXTRACTOR.parse_scene([
        "INSUNITS\t4",
        "LAYER\tOBJECT",
        "ENT\tCIRCLE\tOBJECT\t1A\t1,2,0\t5",
        "ENT\tLINE\tOBJECT\t1B\t-1,0,0\t3,4,0",
        "ENT\tTEXT\tDIM\t1C\t0,8,0\t2.5\tR10.0",
    ], tmp_path / "candidate.dwg")

    assert scene["insunits"] == 4
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
