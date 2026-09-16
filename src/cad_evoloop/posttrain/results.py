"""Export read-only drawing results with explicit, separately attributed adjudication."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from cad_evoloop.evaluation.human_review import HumanReviewStore
from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from .drawing_qa import workspace_path

ROOT = Path(__file__).resolve().parents[3]


def answer_value(value):
    return value.get("answer") if isinstance(value, dict) else value


def display_answer(value, run):
    if value is None:
        return ""
    options = {row["value"]: row["label"] for row in run["task"].get("options", [])}
    return options.get(value, str(value))


def raw_outcome(run):
    if run["task_manifest"].get("diagnostic_eligible") is False:
        return "excluded"
    learner = run.get("learner")
    if not learner:
        return "not_run"
    if learner["status"] == "timeout":
        return "timeout"
    if learner.get("passed") is True:
        return "agree"
    if learner.get("passed") is False:
        return "disagree"
    return "pending"


def summarize(rows, mode="adjusted"):
    counts = Counter(row[mode] for row in rows)
    attempted = sum(row["attempted"] for row in rows)
    submitted = sum(row["submitted"] for row in rows)
    agreed = counts["agree"]
    return {"selected": len(rows), "attempted": attempted, "submitted": submitted,
            "counts": dict(counts), "agreement_all": agreed / attempted if attempted else None,
            "agreement_submitted": agreed / submitted if submitted else None,
            "observations": sum(row["observations"] for row in rows),
            "elapsed_seconds": sum(row["elapsed_seconds"] for row in rows)}


def collect(config_path: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    reviews = {(r["batch"], r["task"]): r for r in config["semantic_reviews"]}
    if len(reviews) != len(config["semantic_reviews"]):
        raise ValueError("Duplicate semantic assessment")
    consumed = set()
    batches, rows = [], []
    for batch in config["batches"]:
        root = workspace_path(ROOT / batch["bundle"])
        store = HumanReviewStore(root / "review-data.json", root / "human-reviews.jsonl")
        response = store.response()
        if not response["integrity"]["ok"]:
            raise ValueError("Review ledger integrity failed")
        superseded = {r.get("supersedes_review_id") for r in response["records"]}
        active = [r for r in response["records"] if r["review_id"] not in superseded]
        bundle = store.bundle
        excluded = {r["question_id"]: r["reasons"] for r in bundle["summary"].get("quarantined", [])}
        batch_rows = []
        for run in bundle["runs"]:
            learner = run.get("learner") or {}
            key = (batch["id"], run["sample_id"])
            expected = answer_value(run["reference_answer"])
            actual = answer_value(run.get("learner_answer"))
            raw = raw_outcome(run)
            adjusted, basis, note = raw, "automatic", "原始自动判分；标注尚未经人工确认。"
            if key in reviews:
                review = reviews[key]
                consumed.add(key)
                if expected != review["expected"] or actual != review["answer"] or raw != "pending":
                    raise ValueError(f"Semantic assessment no longer matches its evidence: {key}")
                if review["outcome"] not in {"agree", "disagree"}:
                    raise ValueError("Invalid semantic assessment outcome")
                adjusted, basis, note = review["outcome"], "assistant_semantic", review["note"]
            human = [r for r in active if r["binding"]["target_id"] == run["target_id"]
                     and r["binding"]["attempt_id"] == run["selected_attempt_id"]
                     and r["recommended_action"] in {"override_fail", "override_pass"}]
            if human:
                if actual is None or raw == "excluded":
                    raise ValueError("Cannot count an unsubmitted/excluded answer as human graded")
                actions = {r["recommended_action"] for r in human}
                adjusted = "pending" if len(actions) != 1 else ("agree" if "override_pass" in actions else "disagree")
                basis, note = "human", "\n".join(r["notes"] for r in human)
            row = {"batch": batch["id"], "task": run["sample_id"],
                "family": run["task_manifest"]["task_type"], "query": run["task"]["query"],
                "expected": display_answer(expected, run), "answer": display_answer(actual, run),
                "raw": raw, "adjusted": adjusted, "basis": basis, "note": note,
                "attempted": bool(learner) and raw != "excluded", "submitted": actual is not None and raw != "excluded",
                "observations": learner.get("observations", 0), "elapsed_seconds": learner.get("elapsed_seconds", 0),
                "human_review_ids": [r["review_id"] for r in human],
                "excluded_reasons": excluded.get(run["sample_id"], []),
                "bundle_sha256": bundle["bundle_sha256"], "target_id": run["target_id"],
                "image": f"/bundles/{batch['id']}/{run['input_images'][0]}",
                "review_url": f"/?batch={batch['id']}&task={run['sample_id']}"}
            rows.append(row)
            batch_rows.append(row)
        batches.append({**batch, "bundle_sha256": bundle["bundle_sha256"],
                        "ledger_head_sha256": response["integrity"]["head_sha256"],
                        "raw": summarize(batch_rows, "raw"), "adjusted": summarize(batch_rows)})
    if consumed != set(reviews):
        raise ValueError("Semantic assessment references a missing task")
    return {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": "kimi-k3", "harness": "native-kimi-code-public-mcp-only", "timeout_seconds": 600,
            "config_sha256": sha256_file(config_path), "batches": batches, "rows": rows,
            "diagnostics": config.get("diagnostics", []),
            "raw": summarize(rows, "raw"), "adjusted": summarize(rows),
            "caution": "候选标注一致率，不是专家 GT 准确率。语义核对为助手事后文本判断，未验证附加解释。各批次非同题对照。"}


def export(config_path: Path, output: Path):
    output = workspace_path(output, fresh=True)
    report = collect(workspace_path(config_path))
    app = ROOT / "apps/posttrain-review"
    html = (app / "results.template.html").read_text(encoding="utf-8")
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    html = html.replace("__REPORT_DATA__", payload)
    html = html.replace("__REPORT_STYLE__", (app / "results.css").read_text(encoding="utf-8"))
    html = html.replace("__REPORT_SCRIPT__", (app / "results.js").read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    write_json_atomic(output / "results-data.json", report)
    (output / "results.html").write_text(html, encoding="utf-8")
    return {"output": str(output), "batches": len(report["batches"]), **report["adjusted"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.config, args.output), ensure_ascii=False))
