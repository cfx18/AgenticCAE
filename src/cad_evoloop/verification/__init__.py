"""Deterministic and visual CAD verification."""

from .verify import verify_scene
from .render_core_console import render_dwg_core

__all__ = ["render_dwg_core", "verify_scene"]
