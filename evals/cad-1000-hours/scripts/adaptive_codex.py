"""Inspect and operate adaptive CAD self-improvement sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from adaptive import AdaptiveSession, build_diagnostic
from adaptive.session import write_json


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--session", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--session", required=True)

    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--session", required=True)
    diagnose.add_argument("--sample-id", required=True)
    diagnose.add_argument("--run-id", required=True)
    diagnose.add_argument("--attempt-id", required=True)
    diagnose.add_argument("--stage", required=True)
    diagnose.add_argument("--component", required=True)
    diagnose.add_argument(
        "--outcome", required=True,
        choices=(
            "success", "evaluation_failure", "coverage_gap",
            "infrastructure_error", "agent_error",
        ),
    )
    diagnose.add_argument("--summary", required=True)
    diagnose.add_argument("--return-code", type=int)
    diagnose.add_argument("--retryable", action="store_true")
    diagnose.add_argument("--verdict", type=Path)
    diagnose.add_argument("--stderr", type=Path)
    diagnose.add_argument("--stdout", type=Path)
    diagnose.add_argument("--candidate", type=Path)
    diagnose.add_argument("--output", type=Path, required=True)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--session", required=True)
    decide.add_argument("--diagnostic", type=Path, required=True)
    decide.add_argument("--model", default="gpt-5.5")
    decide.add_argument("--reasoning-effort", default="medium")
    decide.add_argument("--output", type=Path)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--session", required=True)
    apply.add_argument("--diagnostic", type=Path, required=True)
    apply.add_argument("--action", type=Path, required=True)
    apply.add_argument("--model", default="gpt-5.5")
    apply.add_argument("--reasoning-effort", default="medium")

    args = parser.parse_args()
    session = AdaptiveSession(EVAL_ROOT, args.session, create=args.command == "init")
    if args.command == "init":
        print(json.dumps(read_json(session.manifest_path), indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(read_json(session.manifest_path), indent=2, ensure_ascii=False))
    elif args.command == "diagnose":
        diagnostic = build_diagnostic(
            sample_id=args.sample_id, run_id=args.run_id, attempt_id=args.attempt_id,
            stage=args.stage, component=args.component, outcome=args.outcome,
            summary=args.summary, retryable=args.retryable, return_code=args.return_code,
            verdict=read_json(args.verdict) if args.verdict else None,
            stderr_path=args.stderr, stdout_path=args.stdout,
            artifacts=((args.candidate, "candidate"),),
        )
        write_json(args.output, diagnostic)
        print(json.dumps(diagnostic, indent=2, ensure_ascii=False))
    elif args.command == "decide":
        action = session.decide(
            read_json(args.diagnostic), model=args.model,
            effort=args.reasoning_effort, executable=shutil.which("codex") or "codex",
        )
        if args.output:
            write_json(args.output, action)
        print(json.dumps(action, indent=2, ensure_ascii=False))
    elif args.command == "apply":
        result = session.apply_patch(
            read_json(args.action), read_json(args.diagnostic), model=args.model,
            effort=args.reasoning_effort, executable=shutil.which("codex") or "codex",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
