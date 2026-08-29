"""Stable project paths shared by compatibility CLIs and research tooling."""

from __future__ import annotations

import os
from pathlib import Path


def project_root(start: str | Path | None = None) -> Path:
    configured = os.environ.get("CAD_EVOLOOP_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not (root / "pyproject.toml").is_file():
            raise FileNotFoundError(f"CAD_EVOLOOP_ROOT is not a project root: {root}")
        return root

    origin = Path(start).resolve() if start is not None else Path(__file__).resolve()
    if origin.is_file():
        origin = origin.parent
    for candidate in (origin, *origin.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "evals/cad-1000-hours").is_dir():
            return candidate
    raise FileNotFoundError("Could not locate the CAD-EvoLoop project root")


def evaluation_root(start: str | Path | None = None) -> Path:
    return project_root(start) / "evals/cad-1000-hours"
