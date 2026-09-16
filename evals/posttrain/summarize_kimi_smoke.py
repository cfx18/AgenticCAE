"""Collect native answers and observed images without rerunning a model."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cad_evoloop.agent.events import GENESIS_HASH, validate_event
from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from cad_evoloop.posttrain.bundle import contained_file


def collect(run_path: Path) -> dict:
    metadata = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    if metadata["status"] == "running":
        raise ValueError(f"Still running: {run_path}")
    episode = run_path / "episode"
    state = json.loads((episode / "episode.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (episode / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    previous = GENESIS_HASH
    observations = {}
    for index, event in enumerate(events, 1):
        validate_event(event, project_id=state["episode_id"], expected_sequence=index, expected_previous_hash=previous)
        previous = event["event_hash"]
        payload = event["payload"]
        if event["event_type"] == "observation_returned":
            if sha256_file(episode / payload["image"]) != payload["sha256"]:
                raise ValueError("Observed image changed")
            observations[payload["observation_id"]] = {**payload, "findings": [],
                "actual_image_path": str((episode / payload["image"]).relative_to(ROOT)).replace("\\", "/")}
        elif event["event_type"] == "observation_conclusion":
            observations[payload["observation_id"]]["findings"].append(payload["public_conclusion"])
    native = [json.loads(line) for line in (run_path / "kimi-events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    calls = [call["function"]["name"] for event in native for call in event.get("tool_calls", [])]
    metadata.update({"run_path": run_path.relative_to(ROOT).as_posix(), "event_chain_verified": True,
                     "observed_tools": dict(Counter(calls)), "unexpected_tools": sorted(set(calls) - set(metadata["allowed_tools"])),
                     "image_observations": list(observations.values()),
                     "native_events_sha256": sha256_file(run_path / "kimi-events.jsonl"),
                     "episode_events_sha256": sha256_file(episode / "events.jsonl")})
    if state.get("status") == "submitted":
        for item in state["submission"]["files"]:
            if item["source"] == "answer.json":
                path = contained_file(episode, item["snapshot"])
                if sha256_file(path) != item["sha256"]:
                    raise ValueError("Submitted answer snapshot changed")
                metadata["answer"] = json.loads(path.read_text(encoding="utf-8"))
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError("Use a fresh summary path")
    rows = [collect(path.parent) for root in args.runs for path in sorted(root.resolve().glob("*/run.json"))]
    counts = Counter(row["task_id"] for row in rows)
    if any(count != 1 for count in counts.values()):
        raise ValueError("Duplicate task attempts; choose the predeclared run, not the best outcome")
    graded = [row for row in rows if row["status"] == "graded"]
    summary = {"harness": "native-kimi-code-public-mcp-only", "model": "kimi-k3",
               "attempted": len(rows), "graded": len(graded),
               "passed": sum(row["passed"] is True for row in graded),
               "ungraded": len(rows) - len(graded), "observations": sum(row["observations"] for row in rows),
               "findings": sum(row["findings"] for row in rows),
               "unexpected_tools": sorted({tool for row in rows for tool in row["unexpected_tools"]}),
               "scope": "Perception smoke only; no AutoCAD, CAD code execution, GT feedback, SFT or RL.",
               "not_run": ["repair-01", "repair-02", "repair-03", "reconstruct-01", "reconstruct-02"],
               "runs": rows}
    if args.bundle:
        manifests = {path.parent.name: json.loads(path.read_text(encoding="utf-8"))
                     for path in (args.bundle / "tasks").glob("*/manifest.json")}
        summary["not_run"] = sorted(set(manifests) - {row["task_id"] for row in rows})
        summary["score_semantics"] = sorted({row.get("score_semantics", "reference_agreement") for row in rows})
        groups = {}
        for row in rows:
            family = manifests[row["task_id"]]["task_type"]
            group = groups.setdefault(family, {"attempted": 0, "graded": 0, "agreed": 0, "ungraded": 0})
            group["attempted"] += 1
            group["graded" if row["status"] == "graded" else "ungraded"] += 1
            group["agreed"] += row.get("passed") is True
        summary["by_task_type"] = groups
    write_json_atomic(output, summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}))


if __name__ == "__main__":
    main()
