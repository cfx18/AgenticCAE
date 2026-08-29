"""Command-line interface for the CAD evaluation run ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = EVAL_ROOT.parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))

from cad_evoloop.ledger import RunLedger


DEFAULT_SOURCES = (
    EVAL_ROOT.parents[1] / ".agents/skills/autocad-image-modeling/SKILL.md",
    EVAL_ROOT.parents[1] / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py",
    WORKSPACE / "src/cad_evoloop/backends/autocad/audited.py",
    WORKSPACE / "src/cad_evoloop/verification/extract_autocad.py",
    WORKSPACE / "src/cad_evoloop/verification/verify.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/evaluate.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/provider.py",
    WORKSPACE / "src/cad_evoloop/verification/vlm/render_scene.py",
    EVAL_ROOT / "verifier/vlm/visual-verdict.schema.json",
    EVAL_ROOT / "runledger/ledger.py",
    EVAL_ROOT / "runledger/schemas/run.schema.json",
    EVAL_ROOT / "runledger/schemas/trajectory-event.schema.json",
    Path(__file__).resolve(),
)


def payload(value: str | None) -> dict:
    return json.loads(value) if value else {}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--sample-id", required=True)
    start.add_argument("--run-id")
    start.add_argument("--parent-run-id")
    start.add_argument("--agent-id")
    start.add_argument("--model")
    start.add_argument("--source", action="append", default=[])
    start.add_argument("--input", action="append", default=[])
    start.add_argument("--no-default-sources", action="store_true")

    attempt = commands.add_parser("attempt")
    attempt.add_argument("--run", required=True)
    attempt.add_argument("--label", required=True)
    attempt.add_argument("--status", default="running")
    attempt.add_argument("--parent")
    attempt.add_argument("--summary", default="")

    artifact = commands.add_parser("artifact")
    artifact.add_argument("--run", required=True)
    artifact.add_argument("--attempt", required=True)
    artifact.add_argument("--role", required=True)
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--reference", action="store_true")

    event = commands.add_parser("event")
    event.add_argument("--run", required=True)
    event.add_argument("--type", required=True)
    event.add_argument("--summary", required=True)
    event.add_argument("--status", default="pass")
    event.add_argument("--actor", default="agent")
    event.add_argument("--attempt")
    event.add_argument("--payload-json")

    finish = commands.add_parser("finish")
    finish.add_argument("--run", required=True)
    finish.add_argument("--attempt", required=True)
    finish.add_argument("--verdict", required=True)

    show = commands.add_parser("show")
    show.add_argument("--run", required=True)

    listing = commands.add_parser("list")
    listing.add_argument("--sample-id")

    reuse = commands.add_parser("reuse")
    reuse.add_argument("--sample-id", required=True)
    reuse.add_argument("--role", default="candidate")
    reuse.add_argument("--output")

    diff = commands.add_parser("diff")
    diff.add_argument("--from-run", required=True)
    diff.add_argument("--to-run", required=True)

    integrity = commands.add_parser("verify-integrity")
    integrity.add_argument("--run", required=True)

    ingest = commands.add_parser("ingest-mcp")
    ingest.add_argument("--run", required=True)
    ingest.add_argument("--path")

    commands.add_parser("reindex")
    return root


def main() -> None:
    args = parser().parse_args()
    ledger = RunLedger(EVAL_ROOT)
    if args.command == "start":
        sources = [Path(item) for item in args.source]
        if not args.no_default_sources:
            sources = [*DEFAULT_SOURCES, *sources]
        run_dir = ledger.start(
            args.sample_id,
            run_id=args.run_id,
            parent_run_id=args.parent_run_id,
            agent={"system": "codex", "agent_id": args.agent_id, "model": args.model},
            source_paths=sources,
            input_paths=args.input,
        )
        result = {"run_id": run_dir.name, "path": str(run_dir)}
    elif args.command == "attempt":
        result = {"attempt_id": ledger.add_attempt(
            args.run, label=args.label, status=args.status,
            parent_attempt_id=args.parent, summary=args.summary,
        )}
    elif args.command == "artifact":
        result = ledger.add_artifact(
            args.run, args.attempt, args.path, role=args.role, copy=not args.reference,
        )
    elif args.command == "event":
        result = ledger.event(
            args.run, args.type, args.summary, status=args.status,
            actor=args.actor, attempt_id=args.attempt, payload=payload(args.payload_json),
        )
    elif args.command == "finish":
        result = ledger.finish(args.run, args.attempt, args.verdict)
    elif args.command == "show":
        result = ledger.show(args.run)
    elif args.command == "list":
        result = ledger.list_runs(args.sample_id)
    elif args.command == "reuse":
        result = ledger.reusable_artifact(
            args.sample_id, role=args.role, output=args.output,
        )
    elif args.command == "diff":
        result = ledger.diff_runs(args.from_run, args.to_run)
    elif args.command == "verify-integrity":
        result = ledger.verify_integrity(args.run)
    elif args.command == "ingest-mcp":
        result = ledger.ingest_mcp_audit(args.run, args.path)
    else:
        result = {"indexed": ledger.reindex()}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
