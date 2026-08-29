"""Immutable campaign manifests for reproducible CAD agent evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Iterable

from .isolation import input_inventory, sha256_file


SCHEMA_VERSION = "1.0"
MODES = {"development", "pilot", "frozen-evaluation"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def value_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _git_state(workspace: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(workspace), *args], capture_output=True, text=True,
            check=False, encoding="utf-8", errors="replace",
        ).stdout.strip()

    status = run("status", "--porcelain=v1")
    diff = run("diff", "--binary", "HEAD")
    return {
        "commit": run("rev-parse", "HEAD") or None,
        "dirty": bool(status),
        "working_tree_sha256": value_digest({"status": status, "diff": diff}) if status else None,
    }


def _evaluator_inventory(sample_dir: Path) -> list[dict[str, Any]]:
    paths = [
        path for name in ("rubrics.json", "metadata.json")
        if (path := sample_dir / name).is_file()
    ]
    output_dir = sample_dir / "output_files"
    if output_dir.is_dir():
        paths.extend(sorted(path for path in output_dir.rglob("*") if path.is_file()))
    return [
        {
            "path": path.relative_to(sample_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "role": (
                "rubric" if path.name == "rubrics.json"
                else "metadata" if path.name == "metadata.json"
                else "reference-output"
            ),
        }
        for path in paths
    ]


def _split_membership(split: dict[str, Any], sample_ids: list[str]) -> dict[str, Any]:
    development = set(split.get("development", []))
    holdout = set(split.get("holdout", []))
    unknown = sorted(set(sample_ids) - development - holdout)
    return {
        "development": sorted(set(sample_ids) & development),
        "holdout": sorted(set(sample_ids) & holdout),
        "unknown": unknown,
    }


def build_campaign_manifest(
    *,
    campaign_id: str,
    mode: str,
    eval_root: Path,
    sample_ids: Iterable[str],
    models: Iterable[dict[str, Any]],
    source_paths: Iterable[Path],
    execution: dict[str, Any],
    split_path: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"Unsupported campaign mode: {mode}")
    eval_root = Path(eval_root).resolve()
    workspace = eval_root.parents[1]
    samples = list(sample_ids)
    if not samples or len(samples) != len(set(samples)):
        raise ValueError("Campaign samples must be non-empty and unique")
    dataset_manifest_path = eval_root / "manifest.json"
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    split_path = Path(split_path or eval_root / "improvement/split.json").resolve()
    split = json.loads(split_path.read_text(encoding="utf-8"))
    membership = _split_membership(split, samples)
    if mode == "development" and (membership["holdout"] or membership["unknown"]):
        raise ValueError("Development campaign contains holdout or unknown samples")
    if mode == "frozen-evaluation" and membership["development"]:
        raise ValueError("Frozen evaluation must not contain development samples")
    if mode == "frozen-evaluation" and not (
        split.get("purpose") == "paper-final" and split.get("sealed") is True
    ):
        raise ValueError("Frozen evaluation requires a sealed paper-final split")

    git_state = _git_state(workspace)
    if mode == "frozen-evaluation" and (
        not git_state.get("commit") or git_state.get("dirty")
    ):
        raise ValueError("Frozen evaluation requires a clean committed source tree")

    source_records = []
    for path in sorted({Path(path).resolve() for path in source_paths}):
        if not path.is_file():
            raise FileNotFoundError(path)
        source_records.append({
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    sample_records = []
    for sample_id in samples:
        sample_dir = eval_root / "samples" / sample_id
        if not sample_dir.is_dir():
            raise FileNotFoundError(sample_dir)
        rubric = sample_dir / "rubrics.json"
        sample_records.append({
            "sample_id": sample_id,
            "visible_inputs": input_inventory(sample_dir),
            "evaluator_rubric_sha256": sha256_file(rubric),
            "evaluator_only": _evaluator_inventory(sample_dir),
        })

    body = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "mode": mode,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "dataset": {
            "source": dataset_manifest.get("source"),
            "revision": dataset_manifest.get("revision"),
            "license": dataset_manifest.get("license"),
            "manifest_sha256": sha256_file(dataset_manifest_path),
            "split_sha256": sha256_file(split_path),
            "split_purpose": split.get("purpose", "development-pilot"),
            "split_sealed": bool(split.get("sealed", False)),
            "membership": membership,
        },
        "models": list(models),
        "execution": execution,
        "source": {"git": git_state, "files": source_records},
        "samples": sample_records,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    body["manifest_sha256"] = value_digest(body)
    return body


def validate_campaign_manifest(manifest: dict[str, Any]) -> None:
    digest = manifest.get("manifest_sha256")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if not isinstance(digest, str) or digest != value_digest(body):
        raise ValueError("Campaign manifest digest mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported campaign manifest schema")
    if manifest.get("mode") not in MODES:
        raise ValueError("Unsupported campaign mode")


def write_immutable_manifest(path: Path, manifest: dict[str, Any]) -> None:
    validate_campaign_manifest(manifest)
    path = Path(path)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        validate_campaign_manifest(existing)
        if existing != manifest:
            raise FileExistsError(f"Campaign manifest is immutable: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
