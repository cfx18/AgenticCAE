"""Deterministic local materialization of a family-diverse BenchCAD pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cad_evoloop.evaluation.benchcad_campaign import _run_bridge


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}\0{value}".encode()).hexdigest()


def select_family_diverse(rows: list[dict[str, str]], count: int, seed: str) -> list[dict[str, str]]:
    if count < 1:
        raise ValueError("count must be positive")
    best: dict[str, dict[str, str]] = {}
    for row in rows:
        family, stem = row["family"], row["stem"]
        current = best.get(family)
        if current is None or _rank(seed, stem) < _rank(seed, current["stem"]):
            best[family] = row
    selected = sorted(best.values(), key=lambda row: _rank(seed, f"family:{row['family']}"))
    if len(selected) < count:
        raise ValueError(f"requested {count} families, dataset has only {len(selected)}")
    return selected[:count]


def materialize_benchcad_pilot(
    *, parquet_dir: Path, upstream: Path, output: Path, count: int = 30,
    seed: str = "evocad-benchcad-family-v1",
    dataset_revision: str = "5919f578ab09ec283603a082fab07c7639ab56eb",
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    parquet_dir = parquet_dir.resolve()
    upstream = upstream.resolve()
    output = output.resolve()
    shards = sorted(parquet_dir.glob("*.parquet"))
    if not shards:
        raise FileNotFoundError(f"No parquet shards found in {parquet_dir}")
    metadata: list[dict[str, str]] = []
    for shard in shards:
        table = pq.read_table(shard, columns=["stem", "family", "difficulty", "variant"])
        metadata.extend(table.to_pylist())
    family_count = len({row["family"] for row in metadata})
    candidates = select_family_diverse(metadata, family_count, seed)
    by_stem = {row["stem"]: row for row in candidates}
    material: dict[str, dict[str, Any]] = {}
    for shard in shards:
        for batch in pq.ParquetFile(shard).iter_batches(
            batch_size=128, columns=["stem", "family", "difficulty", "variant", "code", "composite_png"],
        ):
            for row in batch.to_pylist():
                if row["stem"] in by_stem:
                    material[row["stem"]] = row
        if len(material) == len(candidates):
            break
    missing = sorted(set(by_stem) - set(material))
    if missing:
        raise RuntimeError(f"Selected rows were not found in parquet payload: {missing}")

    codes = output / "codes"
    steps = output / "steps"
    source_composites = output / "_source_composites"
    codes.mkdir(parents=True, exist_ok=True)
    steps.mkdir(parents=True, exist_ok=True)
    source_composites.mkdir(parents=True, exist_ok=True)
    python = upstream / ".venv/Scripts/python.exe"
    records = []
    failures = []
    self_checks = output / "_self_checks"
    self_checks.mkdir(parents=True, exist_ok=True)
    for selection in candidates:
        if len(records) >= count:
            break
        row = material[selection["stem"]]
        stem = row["stem"]
        code_path = codes / f"{stem}.py"
        step_path = steps / f"{stem}.step"
        png_path = steps / f"{stem}.png"
        code_path.write_text(row["code"], encoding="utf-8", newline="\n")
        composite = row["composite_png"]
        png_bytes = composite.get("bytes") if isinstance(composite, dict) else composite
        if not isinstance(png_bytes, bytes):
            raise ValueError(f"composite_png has no bytes for {stem}")
        (source_composites / f"{stem}.png").write_bytes(png_bytes)
        if not step_path.is_file():
            rendered = output / "_materialize_renders" / f"{stem}.png"
            result = _run_bridge(python, [
                "--upstream", str(upstream), "execute", "--code", str(code_path),
                "--step", str(step_path), "--render", str(rendered),
                "--timeout", "600", "--parallel-scale", "0.55", "--view-size", "256",
                "--trusted-source",
            ], 660)
            if not result.get("ok"):
                failures.append({"record_id": stem, "error": result})
                continue
        check_path = self_checks / f"{stem}.json"
        if check_path.is_file():
            check = json.loads(check_path.read_text(encoding="utf-8"))
        else:
            check = _run_bridge(python, [
                "--upstream", str(upstream), "validate-step", "--step", str(step_path),
                "--resolution", "64",
            ], 360)
            check_path.write_text(json.dumps(check, indent=2) + "\n", encoding="utf-8")
        if not check.get("ok"):
            failures.append({"record_id": stem, "error": check})
            continue
        render_result = _run_bridge(python, [
            "--upstream", str(upstream), "render", "--step", str(step_path),
            "--render", str(png_path), "--parallel-scale", "0.55", "--view-size", "256",
        ], 360)
        if not render_result.get("ok"):
            failures.append({"record_id": stem, "error": render_result})
            continue
        records.append({
            "record_id": stem, "family": row["family"], "difficulty": row["difficulty"],
            "variant": row["variant"], "code_path": f"codes/{stem}.py",
            "step_path": f"steps/{stem}.step",
        })
    (output / "records.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8",
    )
    result = {
        "protocol": "evocad-benchcad-selection-v1", "selection_kind": "one-per-family",
        "seed": seed, "requested": count, "materialized": len(records), "failures": failures,
        "dataset_revision": dataset_revision, "parquet_dir": str(parquet_dir),
        "upstream_commit": __import__("subprocess").check_output(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True,
        ).strip(),
        "records": records,
    }
    (output / "selection.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return result
