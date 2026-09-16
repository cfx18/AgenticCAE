"""Hash-bound task packages. Packaging is not an OS security boundary."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import shutil

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic


VERSION = "evocad-posttrain-v1"
SECTIONS = {"public", "private", "reference", "tests", "provenance"}


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def contained_file(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
        raise ValueError(f"Unsafe relative path: {name}")
    root = root.resolve()
    path = root.joinpath(*relative.parts)
    current = path
    while current != root:
        if is_link(current):
            raise ValueError("Links and junctions are not allowed in task assets")
        current = current.parent
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing or escaping asset: {name}")
    return path


def seal_bundle(root: Path, metadata: dict) -> dict:
    """Seal a freshly constructed bundle; changing it creates a new task version."""
    if (root / "manifest.json").exists():
        raise FileExistsError("Task already sealed")
    records = []
    for path in sorted(root.rglob("*")):
        if is_link(path):
            raise ValueError("Task assets cannot be links")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name.split("/")[0] not in SECTIONS:
            raise ValueError(f"Undeclared task section: {name}")
        records.append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    manifest = {**metadata, "schema_version": VERSION, "assets": records, "status": "pending_human_review"}
    write_json_atomic(root / "manifest.json", manifest)
    validate_bundle(root)
    return manifest


def validate_bundle(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != VERSION:
        raise ValueError("Unsupported task schema")
    for field in ("task_id", "task_type", "ancestry", "license", "split"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Missing {field}")
    declared = set()
    for asset in manifest["assets"]:
        name = asset["path"]
        if name in declared or name.split("/")[0] not in SECTIONS:
            raise ValueError("Duplicate or undeclared task asset")
        declared.add(name)
        path = contained_file(root, name)
        if path.stat().st_size != asset["bytes"] or sha256_file(path) != asset["sha256"]:
            raise ValueError(f"Task asset changed: {name}")
    required = {"public/task.json", "private/verifier.json", "reference/answer.json"}
    if not required <= declared:
        raise ValueError("Incomplete task bundle")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {"manifest.json"}
    if declared != actual:
        raise ValueError("Unlisted or missing task assets")
    public = json.loads((root / "public/task.json").read_text(encoding="utf-8"))
    if public.get("task_id") != manifest["task_id"] or not public.get("query"):
        raise ValueError("Public task identity or query missing")
    return manifest


def export_public(root: Path, destination: Path) -> list[dict]:
    manifest = validate_bundle(root)
    if destination.exists():
        raise FileExistsError("Reset requires a new episode directory")
    inventory = [row for row in manifest["assets"] if row["path"].startswith("public/")]
    destination.mkdir(parents=True)
    for row in inventory:
        relative = PurePosixPath(row["path"]).relative_to("public")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(contained_file(root, row["path"]), target)
    return [{**row, "path": str(PurePosixPath(row["path"]).relative_to("public"))} for row in inventory]
