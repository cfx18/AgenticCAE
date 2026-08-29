"""Construct and audit the exact file bundle visible to a drawing agent."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
from typing import Any


VISIBLE_ROOT_FILES = {"task_desc.json"}
FORBIDDEN_NAMES = {"rubrics.json", "metadata.json", "output_files"}
FORBIDDEN_EVENT_MARKERS = (
    "rubrics.json",
    "metadata.json",
    "output_files",
    "/samples/",
    "\\samples\\",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def visible_input_paths(sample_dir: Path) -> list[Path]:
    sample_dir = Path(sample_dir).resolve()
    paths = [sample_dir / name for name in sorted(VISIBLE_ROOT_FILES)]
    input_dir = sample_dir / "input_files"
    if input_dir.is_dir():
        paths.extend(sorted(path for path in input_dir.rglob("*") if path.is_file()))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing declared agent inputs: {missing}")
    return paths


def input_inventory(sample_dir: Path) -> list[dict[str, Any]]:
    sample_dir = Path(sample_dir).resolve()
    return [
        {
            "path": path.relative_to(sample_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "role": "task" if path.name == "task_desc.json" else "input",
        }
        for path in visible_input_paths(sample_dir)
    ]


def export_agent_inputs(sample_dir: Path, destination: Path) -> list[dict[str, Any]]:
    sample_dir = Path(sample_dir).resolve()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError(f"Agent input destination is not empty: {destination}")
    inventory = input_inventory(sample_dir)
    for record in inventory:
        source = sample_dir / record["path"]
        target = destination / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    assert_isolated_agent_bundle(destination)
    return inventory


def assert_isolated_agent_bundle(bundle: Path) -> None:
    bundle = Path(bundle).resolve()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Agent bundle must not contain symlinks: {path}")
        relative = path.relative_to(bundle)
        if any(part in FORBIDDEN_NAMES for part in relative.parts):
            raise ValueError(f"Evaluator-only asset leaked into agent bundle: {relative}")
        if path.is_file() and not (
            relative.as_posix() in VISIBLE_ROOT_FILES or relative.parts[0] == "input_files"
        ):
            raise ValueError(f"Undeclared agent-visible file: {relative}")


def find_forbidden_event_references(text: str) -> list[str]:
    normalized = text.casefold()
    return sorted(marker for marker in FORBIDDEN_EVENT_MARKERS if marker.casefold() in normalized)
