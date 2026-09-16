"""Run the existing author/audit/bundle/Kimi/review stages as one background job."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from cad_evoloop.posttrain.drawing_qa import (
    audit_questions, author_questions, build_tasks, workspace_path,
)
from cad_evoloop.posttrain.review import export_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authored", type=Path, help="Reuse a complete frozen author stage, not a partial run")
    parser.add_argument("--audited", type=Path, help="Reuse a complete audit bound to the same frozen author stage")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--review-port", type=int, help="Start the final review only after Kimi completes")
    args = parser.parse_args()
    output = workspace_path(args.output, fresh=True)
    output.mkdir(parents=True)
    state = {"status": "running", "stage": "init", "pid": os.getpid(),
             "source_manifest_sha256": sha256_file(args.sources / "sources.json"),
             "plan_sha256": sha256_file(args.plan), "learner_timeout_seconds": args.timeout}

    def update(stage, **values):
        state.update(stage=stage, updated_at=datetime.now(timezone.utc).isoformat(), **values)
        write_json_atomic(output / "job.json", state)
        print(json.dumps(state), flush=True)

    def run(script, *arguments):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, "-u", str(ROOT / "evals/posttrain" / script),
                        *map(str, arguments)], cwd=ROOT, env=environment, check=True)

    try:
        update("author")
        authored = args.authored or output / "teacher"
        if args.authored:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            saved_plan = json.loads((authored / "plan.json").read_text(encoding="utf-8"))
            questions = json.loads((authored / "questions.json").read_text(encoding="utf-8"))["questions"]
            if (plan != saved_plan or len(questions) != len(plan["assignments"])
                    or {q["question_id"] for q in questions} != {a["question_id"] for a in plan["assignments"]}):
                raise ValueError("Reused author stage is incomplete or uses another plan")
        else:
            author_questions(args.sources, args.plan, authored)
        update("blind_audit", authored=str(authored.resolve()))
        audited = args.audited or output / "audit"
        if args.audited:
            audit = json.loads((audited / "audit.json").read_text(encoding="utf-8"))
            questions = json.loads((authored / "questions.json").read_text(encoding="utf-8"))["questions"]
            if (audit["author_questions_sha256"] != sha256_file(authored / "questions.json")
                    or len(audit["answers"]) != len(questions)
                    or {a["question_id"] for a in audit["answers"]} != {q["question_id"] for q in questions}):
                raise ValueError("Reused blind audit is incomplete or bound to other questions")
        else:
            audit_questions(args.sources, authored, audited)
        update("build")
        summary = build_tasks(args.sources, authored, audited, output / "tasks-bundle")
        if not summary["eligible"]:
            raise ValueError("No audited eligible questions; human review is needed")
        export_review(output / "tasks-bundle", output / "annotation-review")
        update("kimi", eligible=summary["eligible"], quarantined=len(summary["quarantined"]),
               annotation_review=str(output / "annotation-review"))
        run("run_kimi_smoke.py", output / "kimi", "--bundle", output / "tasks-bundle", "--timeout", args.timeout)
        update("summarize")
        run("summarize_kimi_smoke.py", output / "metrics.json", output / "kimi", "--bundle", output / "tasks-bundle")
        export_review(output / "tasks-bundle", output / "learner-review", output / "kimi")
        update("complete", status="complete", learner_review=str(output / "learner-review"))
        if args.review_port:
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(ROOT / "evals/posttrain/start-review.ps1"), "-Bundle",
                            str((output / "learner-review").relative_to(ROOT)), "-Port", str(args.review_port)],
                           cwd=ROOT, check=True)
            update("complete", review_url=f"http://127.0.0.1:{args.review_port}/")
    except Exception as error:
        update(state["stage"], status="failed", error=f"{type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()
