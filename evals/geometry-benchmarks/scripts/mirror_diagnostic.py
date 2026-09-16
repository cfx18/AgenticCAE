"""Post-hoc reflection diagnostics; never alters the benchmark alignment policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh

from cad_evoloop.evaluation.geometry_score import score_geometry_files
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root


def reflection_matrix(bounds, axis: int):
    if axis not in (0, 1, 2):
        raise ValueError("axis must be 0, 1 or 2")
    center = np.asarray(bounds, dtype=float).mean(axis=0)
    transform = np.eye(4)
    transform[axis, axis] = -1
    transform[axis, 3] = 2 * center[axis]
    return transform


def run(candidate: Path, ground_truth: Path, output: Path) -> dict:
    candidate, ground_truth, output = (
        path.resolve() for path in (candidate, ground_truth, output)
    )
    output.relative_to(project_root())
    source_hashes = {str(path): sha256_file(path) for path in (candidate, ground_truth)}
    output.mkdir(parents=True, exist_ok=False)
    mesh = trimesh.load_mesh(candidate, process=True)
    rows = []
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "experiment_type": "human-requested-posthoc-mirror-diagnostic",
        "eligible_for_original_agent_score": False,
        "source_hashes": source_hashes,
        "note": "GT-assisted diagnosis, not an autonomous agent correction. "
                "Original verifier retains proper rotations only; no threshold changes.",
        "rows": rows,
    }
    for axis, name in ((None, "control"), (0, "mirror-x"), (1, "mirror-y"), (2, "mirror-z")):
        transform = np.eye(4) if axis is None else reflection_matrix(mesh.bounds, axis)
        path = candidate
        if axis is not None:
            reflected = mesh.copy()
            # apply_transform reverses triangle winding for negative determinants.
            reflected.apply_transform(transform)
            path = output / f"{name}.stl"
            reflected.export(path)
        verdict = score_geometry_files(path, ground_truth, sample_count=20000, voxel_resolution=64)
        verdict_path = output / f"{name}-verdict.json"
        write_json_atomic(verdict_path, verdict)
        row = {
            "variant": name,
            "transform": transform.tolist(),
            "candidate": str(path),
            "candidate_sha256": sha256_file(path),
            "verdict": str(verdict_path),
            "score": verdict["score"],
            "passed": verdict["passed"],
            "metrics": verdict["metrics"],
            "alignment": verdict["alignment"],
        }
        rows.append(row)
        write_json_atomic(output / "diagnostic.json", report)
        print(json.dumps(row), flush=True)
    report["source_integrity_verified"] = all(
        sha256_file(Path(path)) == expected for path, expected in source_hashes.items()
    )
    write_json_atomic(output / "diagnostic.json", report)
    if not report["source_integrity_verified"]:
        raise RuntimeError("Source changed during diagnostic")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.candidate, args.ground_truth, args.output)


if __name__ == "__main__":
    main()
