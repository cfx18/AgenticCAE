"""Validate a native SAT translation and package a disclosed single-fixture trial."""
import json
from pathlib import Path
import zipfile

import cadquery as cq
from cad_evoloop.ledger.ledger import sha256_file

root = Path(__file__).resolve().parents[3]
submission = root / "evals/cadgenbench/submissions/111-astra-ultra"
run = root / "evals/cadgenbench/runs/cadgenbench-111-codex-astra-ultra-autocad-20260916"
native = json.loads((run / "outputs/verification.json").read_text(encoding="utf-8"))
shape = cq.importers.importStep(str(submission / "candidate.step")).val()
box = shape.BoundingBox()
volume = shape.Volume()
relative_error = abs(volume / native["native_volume_mm3"] - 1)
bounds = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax]
expected = native["native_bounds_mm"]["min"] + native["native_bounds_mm"]["max"]
report = {
    "source": "AutoCAD native SAT", "converter": "Installed Ansys SpaceClaim 2024 R2, SAT import / STEP export only",
    "validation": "Local OpenCascade via CadQuery; not official CADGenBench validity or accuracy",
    "step_valid": shape.isValid(), "step_solids": len(shape.Solids()), "step_faces": len(shape.Faces()),
    "native_faces": native["face_count"], "native_volume_mm3": native["native_volume_mm3"],
    "step_volume_mm3": volume, "volume_relative_difference": relative_error, "step_bounds_mm": bounds,
    "max_bound_difference_mm": max(abs(a-b) for a,b in zip(bounds, expected)),
    "source_sat_sha256": sha256_file(run / "outputs/candidate.sat"),
    "step_sha256": sha256_file(submission / "candidate.step"),
    "caveat": "Translator splits analytic faces and introduces a small volume difference. Official scoring applies to the translated STEP, not byte-identical DWG/SAT.",
}
report["accepted"] = report["step_valid"] and report["step_solids"] == 1 and relative_error < 1e-4 and report["max_bound_difference_mm"] < 1e-3
(submission / "conversion-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
assert report["accepted"], report
names = sorted(item["path"] for item in json.loads((submission / "official-input-tree.json").read_text()) if item["type"] == "directory")
assert "111" in names and len(names) >= 49
meta = {
    "submitter_name": "EvoCAD", "submission_name": "Codex Astra Ultra AutoCAD fixture111 diagnostic",
    "agent_url": None, "agree_to_publish": True,
    "notes": "Single-fixture diagnostic: only generation 111 run; all other fixtures missing, aggregate is NOT a benchmark result. GPT-6 Astra ultra, native Codex continuous conversation, AutoCAD2024 MCP, 35.23min. No GT or score feedback. Postrun SAT->STEP via installed SpaceClaim, no remodeling; valid 1 solid, volume differs 0.000733%, faces 330->366. Unvalidated private harness. User authorized public submission.",
}
with zipfile.ZipFile(submission / "submission.zip", "x", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("meta.json", json.dumps(meta, indent=2))
    for name in names:
        archive.writestr(name + "/", "")
    archive.write(submission / "candidate.step", "111/output.step")
print(json.dumps({"verification": report, "package": str(submission / "submission.zip"), "fixtures": len(names)}, indent=2))
