from __future__ import annotations

import json
from pathlib import Path
import zipfile

from cad_evoloop.evaluation.geometry_dataset import materialize_geometry_pilot


def add(archive: zipfile.ZipFile, path: str, value: bytes | str) -> None:
    archive.writestr(path, value.encode() if isinstance(value, str) else value)


def test_materializes_orthographic_and_omnimech_samples(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    output = tmp_path / "output"
    (data / "ortho2cad").mkdir(parents=True)
    (data / "omnimech").mkdir(parents=True)
    (data / "download-manifest.json").write_text("{}", encoding="utf-8")
    with zipfile.ZipFile(data / "ortho2cad/inference.zip", "w") as archive:
        record = {"question_id": 1, "image": "part.png", "text": "make", "ground_truth": "solid = 1"}
        add(archive, "inference/deepcad_test_data_subset100.jsonl", json.dumps(record))
        add(archive, "inference/test100_images_deepcad/part.png", b"png")
        add(archive, "inference/test100_gt_steps_deepcad/part.step", b"step")
    with zipfile.ZipFile(data / "omnimech/omnimech_samples.zip", "w") as archive:
        add(archive, "sample_data/1/drawing_bitmap/1_drawing_bitmap.png", b"png")
        add(archive, "sample_data/1/brep/1_brep.step", b"step")
        add(archive, "sample_data/1/mesh/1_mesh.stl", b"stl")
        add(archive, "sample_data/1/metadata.json", json.dumps({"category": "part"}))
    monkeypatch.setattr("cad_evoloop.evaluation.geometry_dataset.project_root", lambda: tmp_path)

    manifest = materialize_geometry_pilot(
        data_root=data, output_root=output, ortho_count=1, omni_count=1,
    )

    assert manifest["sample_count"] == 2
    assert [item["sample_id"] for item in manifest["samples"]] == [
        "ortho2cad:part", "omnimech:1",
    ]
    assert (output / "ortho2cad/part/ground_truth.py").read_text() == "solid = 1"
    assert (output / "omnimech/1/ground_truth.stl").read_bytes() == b"stl"

