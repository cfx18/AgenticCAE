from __future__ import annotations

import json
from pathlib import Path


def test_multifamily_seed_summary_if_present_is_consistent():
    path = Path("evals/data/posttrain/multifamily-seed-r1/dataset-summary.json")
    if not path.exists():
        return
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["task_count"] == 120
    assert summary["reference_passed"] == 120
    assert set(summary["family_counts"]) == {
        "drawing_qa",
        "orthographic_to_brep",
        "cad_repair_edit",
        "text_image_to_cad_program",
        "cad_software_operation",
        "assembly",
    }
    assert all(value == 20 for value in summary["family_counts"].values())
