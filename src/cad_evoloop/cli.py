"""Stable command-line entry points for CAD-EvoLoop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sys
from typing import Callable

from .evaluation.campaign import validate_campaign_manifest
from .evaluation.metrics import main as metrics_main
from .evaluation.report import generate_campaign_report
from .evaluation.explorer import generate_explorer_bundle
from .paths import project_root


def _run_script(relative: str) -> None:
    runpy.run_path(str(project_root() / relative), run_name="__main__")


def batch() -> None:
    _run_script("evals/cad-1000-hours/scripts/batch_codex.py")


def ledger() -> None:
    _run_script("evals/cad-1000-hours/scripts/run_ledger.py")


def improve() -> None:
    _run_script("evals/cad-1000-hours/scripts/system_improve.py")


def eqc() -> None:
    metrics_main()


def _verify_campaign() -> None:
    parser = argparse.ArgumentParser(description="Validate an immutable campaign manifest")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    value = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_campaign_manifest(value)
    print(json.dumps({"valid": True, "manifest_sha256": value["manifest_sha256"]}))


def _report_campaign() -> None:
    parser = argparse.ArgumentParser(description="Generate an auditable campaign report")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = generate_campaign_report(args.campaign_dir, args.output)
    print(json.dumps(summary, ensure_ascii=False))


def _export_explorer() -> None:
    parser = argparse.ArgumentParser(description="Export cached evidence for the Run Explorer")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render-native", action="store_true")
    args = parser.parse_args()
    payload = generate_explorer_bundle(
        args.campaign_dir, args.output, render_native=args.render_native,
    )
    print(json.dumps({
        "campaign_id": payload["campaign"]["campaign_id"],
        "runs": len(payload["runs"]),
        "output": str((args.output / "explorer-data.json").resolve()),
    }, ensure_ascii=False))


def main() -> None:
    commands: dict[str, tuple[Callable[[], None], str]] = {
        "batch": (batch, "run a model evaluation campaign"),
        "ledger": (ledger, "query the trajectory ledger"),
        "improve": (improve, "manage system improvement proposals"),
        "eqc": (eqc, "compute evidence-qualified completion"),
        "campaign-verify": (_verify_campaign, "validate a campaign manifest"),
        "report": (_report_campaign, "generate campaign tables and paper-ready figures"),
        "explorer-export": (_export_explorer, "export cached trajectories for the Run Explorer"),
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=commands)
    args, remainder = parser.parse_known_args()
    if args.command is None:
        parser.print_help()
        return
    sys.argv = [f"cad-evoloop {args.command}", *remainder]
    commands[args.command][0]()


if __name__ == "__main__":
    main()
