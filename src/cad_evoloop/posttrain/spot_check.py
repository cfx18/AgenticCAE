"""Package an unlabeled, user-selected drawing probe for the existing Kimi runner."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from .bundle import seal_bundle
from .drawing_qa import BOXED_PROTOCOL, render_boxed_image, workspace_path


def build(config_path: Path, output: Path) -> dict:
    config_path = workspace_path(config_path)
    output = workspace_path(output, fresh=True)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = workspace_path(Path(config["source"]))
    qid, query, bbox = config["task_id"], config["query"], config["bbox"]
    if not qid.isascii() or not qid.replace("-", "").isalnum():
        raise ValueError("Unsafe task ID")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 35:
        raise ValueError("Use a short, nonempty question")
    if (len(bbox) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox)
            or not 0 <= bbox[0] < bbox[2] <= 1000 or not 0 <= bbox[1] < bbox[3] <= 1000):
        raise ValueError("Invalid normalized box")
    if sha256_file(source) != config["source_sha256"]:
        raise ValueError("Source image changed")
    task = output / "tasks" / qid
    for section in ("public", "private", "reference", "provenance"):
        (task / section).mkdir(parents=True)
    region = {"label": "A", "bbox": bbox}
    render_boxed_image(source, region, task / "public/drawing-boxed.png")
    public = {"task_id": qid, "query": query, "input_images": ["drawing-boxed.png"],
              "answer_format": {"answer": "short text"}, "answer_file": "answer.json"}
    write_json_atomic(task / "public/task.json", public)
    write_json_atomic(task / "reference/answer.json", {"answer": None})
    write_json_atomic(task / "private/verifier.json", {"kind": "ungraded_answer",
                      "label_status": "unlabeled_probe"})
    write_json_atomic(task / "private/annotation.json", {
        "author": {"query": query, "regions": [region], "answer_evidence": "用户指定的定点诊断，尚无独立参考答案。"},
        "author_model": None, "author_type": "user_selected_assistant_boxed",
        "blind_audit": None, "blind_agreement": None, "human_accepted": False,
        "selection": config.get("selection_note", ""), "config_sha256": sha256_file(config_path)})
    with Image.open(source) as image:
        dimensions = list(image.size)
    write_json_atomic(task / "provenance/source.json", {"source_id": config["source_id"],
        "source_path": str(source), "sha256": config["source_sha256"], "dimensions": dimensions,
        "origin": "existing_geometry_review_input", "rights": "private_research_rights_unverified"})
    seal_bundle(task, {"task_id": qid, "task_type": "line_role", "ancestry": config["source_id"],
        "license": "private_research_rights_unverified", "split": "ungraded_diagnostic_not_training",
        "label_status": "unlabeled_probe", "diagnostic_eligible": True, "protocol": BOXED_PROTOCOL})
    summary = {"kind": "real-drawing-qa-v1", "pilot_id": output.name, "selected": 1, "completed": 1,
        "distinct_parts": 1, "eligible": 1, "human_accepted": 0, "quarantined": [],
        "source_manifest_sha256": sha256_file(task / "provenance/source.json"),
        "protocol": BOXED_PROTOCOL, "label_status": "unlabeled_probe",
        "results": [{"task_id": qid, "task_type": "line_role", "source_id": config["source_id"],
                     "diagnostic_eligible": True, "label_status": "unlabeled_probe"}]}
    write_json_atomic(output / "pilot-summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.config, args.output), ensure_ascii=False))
