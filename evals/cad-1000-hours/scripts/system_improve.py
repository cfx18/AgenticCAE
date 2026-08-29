"""Manage controlled CAD agent system-improvement proposals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = EVAL_ROOT.parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))

from cad_evoloop.supervisor import ImprovementManager


def emit(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    split = subparsers.add_parser("init-split")
    split.add_argument("--seed", type=int, default=20260828)
    split.add_argument("--development", type=int, default=40)

    collect = subparsers.add_parser("collect")

    create = subparsers.add_parser("create")
    create.add_argument("--proposal", required=True)
    create.add_argument(
        "--component", action="append", required=True,
        choices=("prompt", "skill", "mcp", "verifier"),
    )
    create.add_argument("--minimum-evidence-samples", type=int, default=3)

    agent = subparsers.add_parser("agent")
    agent.add_argument("--proposal", required=True)
    agent.add_argument("--model", default="gpt-5.6-sol")
    agent.add_argument("--reasoning-effort", default="medium")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--proposal", required=True)

    report = subparsers.add_parser("report")
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--model", required=True)
    report.add_argument("--tests-passed", action="store_true")

    gate = subparsers.add_parser("gate")
    gate.add_argument("--proposal", required=True)
    gate.add_argument("--baseline-report", type=Path, required=True)
    gate.add_argument("--candidate-report", type=Path, required=True)
    gate.add_argument("--independent-verifier-approval", action="store_true")
    gate.add_argument("--max-sample-regression", type=float, default=2.0)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--proposal", required=True)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--release", required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--proposal", required=True)

    args = parser.parse_args()
    manager = ImprovementManager()
    if args.command == "init-split":
        emit(manager.init_split(seed=args.seed, development=args.development))
    elif args.command == "collect":
        evidence = manager.collect_evidence()
        emit({
            "evidence_count": len(evidence),
            "sample_count": len({item["sample_id"] for item in evidence}),
            "failure_owners": {
                owner: sum(item["diagnosis"]["failure_owner"] == owner for item in evidence)
                for owner in ("drawing", "prompt", "skill", "mcp", "verifier", "task")
            },
        })
    elif args.command == "create":
        path = manager.create_proposal(
            args.proposal, args.component,
            minimum_evidence_samples=args.minimum_evidence_samples,
        )
        emit({"proposal": args.proposal, "path": str(path)})
    elif args.command == "agent":
        emit(manager.run_agent(args.proposal, args.model, args.reasoning_effort))
    elif args.command == "validate":
        emit(manager.validate_static(args.proposal))
    elif args.command == "report":
        emit(manager.build_report(
            args.results, args.output, model=args.model, tests_passed=args.tests_passed,
        ))
    elif args.command == "gate":
        emit(manager.gate(
            args.proposal, args.baseline_report, args.candidate_report,
            independent_verifier_approval=args.independent_verifier_approval,
            max_sample_regression=args.max_sample_regression,
        ))
    elif args.command == "promote":
        emit(manager.promote(args.proposal))
    elif args.command == "rollback":
        emit(manager.rollback(args.release))
    elif args.command == "status":
        emit(json.loads(
            (manager.proposals_root / args.proposal / "manifest.json").read_text(encoding="utf-8")
        ))


if __name__ == "__main__":
    main()
