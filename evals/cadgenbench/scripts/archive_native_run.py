"""Archive a finished native AutoCAD run without rerunning its model or CAD."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from cad_evoloop.agent.models.codex_cli import parse_codex_events
from cad_evoloop.ledger.ledger import sha256_file, utc_now, write_json_atomic
from cad_evoloop.paths import project_root


def archive(task: Path) -> dict:
    root = project_root().resolve()
    task = task.resolve()
    if not task.is_relative_to(root / "evals/cadgenbench/runs"):
        raise ValueError("Expected a CADGenBench run in the current workspace")
    record = json.loads((task / "run.json").read_text(encoding="utf-8"))
    if record["state"] in {"prepared", "running"}:
        raise ValueError("Do not archive an active run")
    attempt = task / "attempts/a001"
    events_path = attempt / "codex-events.jsonl"
    parsed = parse_codex_events(events_path)
    rows = [json.loads(s) for s in events_path.read_text(encoding="utf-8").splitlines() if s.strip()]
    audit_path = attempt / "mcp-audit.jsonl"
    audit = [json.loads(s) for s in audit_path.read_text(encoding="utf-8").splitlines() if s.strip()]
    destination = task / "recorded-execution"
    destination.mkdir(exist_ok=False)
    snapshots = []
    seen = set()
    for row in audit:
        content = row.get("response", {}).get("result", {}).get("content", [])
        for block in content:
            if block.get("type") != "text":
                continue
            try:
                data = json.loads(block.get("text", ""))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or not data.get("job_dir"):
                continue
            source = Path(data["job_dir"]).resolve()
            if not source.is_relative_to(root / "mcp/jobs") or source in seen:
                continue
            seen.add(source)
            if not source.is_dir():
                continue
            target = destination / "autocad" / source.name
            hashes = {p.relative_to(source): sha256_file(p) for p in source.rglob("*") if p.is_file()}
            shutil.copytree(source, target)
            for relative, digest in hashes.items():
                if sha256_file(target / relative) != digest:
                    raise ValueError(f"Snapshot mismatch: {source / relative}")
            snapshots.append({"job_id": source.name, "tool": row.get("tool"),
                              "source": str(source), "snapshot": str(target),
                              "files": len(hashes), "origin": "postrun_snapshot"})
    write_json_atomic(destination / "native-jobs.json", snapshots)
    messages = [r["item"]["text"] for r in rows if r.get("type") == "item.completed"
                and r.get("item", {}).get("type") == "agent_message"]
    readme = ["# CADGenBench Native AutoCAD Execution", "",
              f"Sample: {record['sample_id']}", f"Model: {record['model']} / {record['effort']}",
              f"Conversation: {parsed['thread_id']}", f"Execution state: {record['state']}", "",
              "Official CADGenBench score: not evaluated. No public upload was made.",
              "Raw CLI events and the MCP audit are under ../attempts/a001/.",
              "Native job snapshots are under autocad/. They preserve the original Lisp and logs.",
              "These are recorded public messages and tool I/O, not unexposed internal reasoning.",
              "", "## Input Prompt", "", (attempt / "action-prompt.txt").read_text(encoding="utf-8"),
              "", "## Agent Messages", ""]
    for index, message in enumerate(messages, 1):
        readme.extend([f"### Message {index}", "", message, ""])
    (destination / "README.md").write_text("\n".join(readme), encoding="utf-8")
    result_path = task / "result.json"
    if not result_path.exists() and record["state"] == "generation_ready_for_review":
        # The first launcher saved its terminal state before an inventory-only typo.
        # That state is set only for rc=0, no timeout, and an existing final DWG.
        write_json_atomic(result_path, {
            "status": record["state"], "return_code": 0, "timed_out": False,
            "elapsed_seconds": record["elapsed_seconds"], "thread_id": parsed["thread_id"],
            "usage": parsed["usage"], "errors": parsed["errors"], "official_score": None,
            "official_evaluation": "not_submitted",
            "record_recovery": "Reconstructed from the persisted terminal run state and CLI events; "
                               "launcher inventory TypeError occurred after model completion. No model/CAD rerun.",
        })
    files = [{"path": p.relative_to(task).as_posix(), "bytes": p.stat().st_size,
              "sha256": sha256_file(p)} for p in sorted(task.rglob("*")) if p.is_file()]
    report = {"schema_version": "1.0", "archived_at": utc_now(), "run": str(task),
              "model": record["model"], "effort": record["effort"],
              "cli_events": len(rows), "mcp_calls": len(audit), "native_jobs": len(snapshots),
              "files": files}
    write_json_atomic(destination / "manifest.json", report)
    return {k: v for k, v in report.items() if k != "files"} | {"file_count": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(archive(args.run), indent=2))
