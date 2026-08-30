"""Materialize external CAD datasets into one immutable EvoCAD sample schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
import zipfile

from ..paths import project_root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_member(archive: zipfile.ZipFile, member: str, destination: Path) -> None:
    if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts:
        raise ValueError(f"Unsafe archive member: {member}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(archive.read(member))


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def materialize_geometry_pilot(
    *,
    data_root: str | Path | None = None,
    output_root: str | Path | None = None,
    bench_count: int = 0,
    ortho_count: int = 10,
    omni_count: int = 10,
) -> dict[str, Any]:
    if bench_count < 0 or ortho_count < 0 or omni_count < 0:
        raise ValueError("Sample counts must be non-negative")
    workspace = project_root()
    data_root = Path(data_root or workspace / ".local/datasets/evocad").resolve()
    output_root = Path(
        output_root or data_root / "materialized/geometry-pilot-v1"
    ).resolve()
    if not output_root.is_relative_to(workspace):
        raise ValueError(f"Output must stay inside the workspace: {output_root}")
    download_manifest = data_root / "download-manifest.json"
    if not download_manifest.is_file():
        raise FileNotFoundError(download_manifest)
    output_root.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    if bench_count:
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise RuntimeError(
                "BenchCAD materialization requires the 'geometry' optional dependency."
            ) from exc
        remaining = bench_count
        for parquet_path in sorted((data_root / "benchcad/code_gen/data").glob("*.parquet")):
            if remaining <= 0:
                break
            rows = parquet.read_table(parquet_path).slice(0, remaining).to_pylist()
            for record in rows:
                stem = record["stem"]
                sample_dir = output_root / "benchcad" / stem
                image = sample_dir / "input.png"
                code = sample_dir / "ground_truth.py"
                metadata = sample_dir / "metadata.json"
                sample_dir.mkdir(parents=True, exist_ok=True)
                image.write_bytes(record["composite_png"]["bytes"])
                code.write_text(record["code"], encoding="utf-8", newline="\n")
                metadata.write_text(json.dumps({
                    "dataset": "benchcad",
                    "family": record["family"],
                    "variant": record["variant"],
                    "difficulty": record["difficulty"],
                    "base_plane": record["base_plane"],
                    "standard": record["standard"],
                }, indent=2), encoding="utf-8")
                samples.append({
                    "sample_id": f"benchcad:{stem}",
                    "dataset": "benchcad",
                    "task": "Generate an executable CadQuery program matching the four rendered CAD views.",
                    "input_images": [_relative(image, output_root)],
                    "ground_truth_code": _relative(code, output_root),
                    "metadata": _relative(metadata, output_root),
                    "family": record["family"],
                    "license": "CC-BY-4.0",
                })
            remaining -= len(rows)
        if remaining:
            raise ValueError(f"BenchCAD contains fewer rows than requested: missing {remaining}")

    ortho_archive = data_root / "ortho2cad/inference.zip"
    with zipfile.ZipFile(ortho_archive) as archive:
        records = archive.read(
            "inference/deepcad_test_data_subset100.jsonl"
        ).decode("utf-8").splitlines()
        for record in [json.loads(line) for line in records[:ortho_count]]:
            stem = Path(record["image"]).stem
            sample_dir = output_root / "ortho2cad" / stem
            image = sample_dir / "input.png"
            step = sample_dir / "ground_truth.step"
            code = sample_dir / "ground_truth.py"
            metadata = sample_dir / "metadata.json"
            _write_member(archive, f"inference/test100_images_deepcad/{stem}.png", image)
            _write_member(archive, f"inference/test100_gt_steps_deepcad/{stem}.step", step)
            code.write_text(record["ground_truth"], encoding="utf-8", newline="\n")
            metadata.write_text(json.dumps({
                "dataset": "ortho2cad",
                "question_id": record["question_id"],
                "source_image": record["image"],
                "instruction": record["text"],
            }, indent=2), encoding="utf-8")
            samples.append({
                "sample_id": f"ortho2cad:{stem}",
                "dataset": "ortho2cad",
                "task": "Reconstruct an editable 3D CAD solid from the dimensioned orthographic drawing.",
                "input_images": [_relative(image, output_root)],
                "ground_truth_step": _relative(step, output_root),
                "ground_truth_code": _relative(code, output_root),
                "metadata": _relative(metadata, output_root),
                "license": None,
            })

    omni_archive = data_root / "omnimech/omnimech_samples.zip"
    with zipfile.ZipFile(omni_archive) as archive:
        available = sorted({
            int(PurePosixPath(name).parts[1])
            for name in archive.namelist()
            if len(PurePosixPath(name).parts) > 2
            and PurePosixPath(name).parts[0] == "sample_data"
            and PurePosixPath(name).parts[1].isdigit()
        })
        for index in available[:omni_count]:
            prefix = f"sample_data/{index}"
            sample_dir = output_root / "omnimech" / str(index)
            image = sample_dir / "input.png"
            step = sample_dir / "ground_truth.step"
            stl = sample_dir / "ground_truth.stl"
            metadata = sample_dir / "metadata.json"
            _write_member(archive, f"{prefix}/drawing_bitmap/{index}_drawing_bitmap.png", image)
            _write_member(archive, f"{prefix}/brep/{index}_brep.step", step)
            _write_member(archive, f"{prefix}/mesh/{index}_mesh.stl", stl)
            _write_member(archive, f"{prefix}/metadata.json", metadata)
            source_metadata = json.loads(metadata.read_text(encoding="utf-8"))
            samples.append({
                "sample_id": f"omnimech:{index}",
                "dataset": "omnimech",
                "task": "Reconstruct the dimensioned mechanical part as one editable 3D CAD solid.",
                "input_images": [_relative(image, output_root)],
                "ground_truth_step": _relative(step, output_root),
                "ground_truth_stl": _relative(stl, output_root),
                "metadata": _relative(metadata, output_root),
                "category": source_metadata.get("category"),
                "license": None,
            })

    manifest = {
        "schema_version": "1.0",
        "campaign_id": "geometry-pilot-v1",
        "download_manifest_sha256": _sha256(download_manifest),
        "sample_count": len(samples),
        "samples": samples,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path)}
