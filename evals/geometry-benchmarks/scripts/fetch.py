"""Fetch the pinned external datasets used by the EvoCAD geometry pilot."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

import requests


WORKSPACE = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = WORKSPACE / ".local" / "datasets" / "evocad"
USER_AGENT = "EvoCAD-geometry-benchmark-fetcher/1.0"

BENCHCAD_REVISION = "5919f578ab09ec283603a082fab07c7639ab56eb"
ORTHO2CAD_REVISION = "5614e7e792635ab3121bcbb4a0bde0df19fb3b3d"


def hf_url(repo: str, revision: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{quote(path, safe='/')}"


def artifact(path: str, size: int, url: str) -> dict[str, Any]:
    return {"path": path, "expected_bytes": size, "url": url}


BENCHCAD_FILES = [
    ("README.md", 1797),
    ("QA/qa_2400.parquet", 32447107),
    *[(f"code_gen/data/code_gen-{index:05d}-of-00018.parquet", size) for index, size in enumerate([
        40904740, 42118467, 41528860, 42329778, 42368598, 40931201,
        43037436, 43212097, 42833368, 41796005, 41826458, 40983892,
        42458465, 41544250, 41826672, 40203596, 39934642, 36585753,
    ])],
    ("edit-bench/data/edit_bench-00000-of-00001.parquet", 114475066),
]

SOURCES = {
    "benchcad": {
        "source": "https://huggingface.co/datasets/BenchCAD/BenchCAD",
        "revision": BENCHCAD_REVISION,
        "license": "CC-BY-4.0",
        "artifacts": [
            artifact(f"benchcad/{path}", size, hf_url("BenchCAD/BenchCAD", BENCHCAD_REVISION, path))
            for path, size in BENCHCAD_FILES
        ],
    },
    "ortho2cad": {
        "source": "https://huggingface.co/datasets/AdityaJoglekar/Ortho2CAD_Orthographic_Drawings",
        "revision": ORTHO2CAD_REVISION,
        "license": None,
        "artifacts": [
            artifact("ortho2cad/README.md", 1239, hf_url(
                "AdityaJoglekar/Ortho2CAD_Orthographic_Drawings", ORTHO2CAD_REVISION, "README.md",
            )),
            artifact("ortho2cad/inference.zip", 18095455, hf_url(
                "AdityaJoglekar/Ortho2CAD_Orthographic_Drawings", ORTHO2CAD_REVISION, "inference.zip",
            )),
            artifact("ortho2cad/f360rec.zip", 145676586, hf_url(
                "AdityaJoglekar/Ortho2CAD_Orthographic_Drawings", ORTHO2CAD_REVISION, "f360rec.zip",
            )),
        ],
    },
    "omnimech": {
        "source": "https://omnimech.dev/",
        "revision": None,
        "license": None,
        "artifacts": [
            artifact("omnimech/omnimech_samples.zip", 48998017, "https://omnimech.dev/res/omnimech_samples.zip"),
            artifact("omnimech/omnimech_code.zip", 138903, "https://omnimech.dev/res/omnimech_code.zip"),
        ],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.is_file() and destination.stat().st_size == expected_bytes:
        print(f"cached {destination.relative_to(DEFAULT_ROOT) if destination.is_relative_to(DEFAULT_ROOT) else destination}")
        return
    if destination.exists():
        destination.unlink()

    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with requests.get(
                url, headers=headers, stream=True, timeout=(30, 120),
            ) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    partial.unlink(missing_ok=True)
                    offset = 0
                mode = "ab" if offset else "wb"
                with partial.open(mode) as stream:
                    downloaded = offset
                    next_report = downloaded + 64 * 1024 * 1024
                    for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                        if not chunk:
                            continue
                        stream.write(chunk)
                        downloaded += len(chunk)
                        if downloaded >= next_report:
                            print(f"  {destination.name}: {downloaded / 1024**2:.1f} MiB")
                            next_report += 64 * 1024 * 1024
            if partial.stat().st_size != expected_bytes:
                raise OSError(
                    f"size mismatch for {destination}: {partial.stat().st_size} != {expected_bytes}"
                )
            partial.replace(destination)
            return
        except (requests.RequestException, OSError) as exc:
            if attempt == 4:
                raise
            print(f"retry {attempt + 1}/4 for {destination.name}: {exc}")
            time.sleep(2 ** attempt)


def fetch_artifact(item: dict[str, Any], data_root: Path) -> dict[str, Any]:
    destination = (data_root / item["path"]).resolve()
    if not destination.is_relative_to(data_root.resolve()):
        raise ValueError(f"Artifact escapes data root: {item['path']}")
    download(item["url"], destination, item["expected_bytes"])
    return {
        "path": destination.relative_to(data_root).as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
        "url": item["url"],
    }


def fetch(names: list[str], data_root: Path, workers: int = 4) -> dict[str, Any]:
    records = []
    for name in names:
        source = SOURCES[name]
        print(f"== {name} ==")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            files = list(pool.map(
                lambda item: fetch_artifact(item, data_root), source["artifacts"]
            ))
        records.append({
            "name": name,
            "source": source["source"],
            "revision": source["revision"],
            "license": source["license"],
            "files": files,
        })
    manifest = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": "geometry-pilot",
        "sources": records,
    }
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "download-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=sorted(SOURCES))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("--workers must be positive")
    names = args.source or list(SOURCES)
    manifest = fetch(names, args.data_root.resolve(), workers=args.workers)
    total = sum(item["bytes"] for source in manifest["sources"] for item in source["files"])
    print(f"verified {total / 1024**3:.2f} GiB in {args.data_root.resolve()}")


if __name__ == "__main__":
    main()
