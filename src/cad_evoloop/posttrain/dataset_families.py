"""CAD post-training dataset-family registry helpers.

The registry is deliberately metadata-first: it records which task families are
ready, which local artifacts support them, and which verifier can score them. It
does not download data or silently promote source material into training gold.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
STATUS = {"active_seeded", "active_partial", "planned", "blocked"}
ARTIFACT_STATUS = {"available", "candidate", "external_pending", "blocked"}
GT_STATUS = {
    "verified_gt",
    "model_proposed_pending_human",
    "candidate_gt_not_imported",
    "no_gt_yet",
}


def workspace_path(path: str | Path) -> Path:
    value = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if value != ROOT and value.is_relative_to(ROOT):
        return value
    raise ValueError(f"Path escapes workspace: {path}")


def load_registry(path: str | Path = "evals/posttrain/cad_data_families.json") -> dict[str, Any]:
    registry_path = workspace_path(path)
    return json.loads(registry_path.read_text(encoding="utf-8"))


def validate_registry(registry: dict[str, Any], *, check_existing: bool = False) -> dict[str, Any]:
    if registry.get("schema_version") != "1.0":
        raise ValueError("Unsupported dataset-family registry schema")
    families = registry.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("Registry must contain at least one family")
    ids = [row.get("family_id") for row in families]
    if len(ids) != len(set(ids)):
        raise ValueError("Family IDs must be unique")
    status_counts: Counter[str] = Counter()
    gt_counts: Counter[str] = Counter()
    checked_artifacts = 0
    missing_artifacts: list[str] = []
    for row in families:
        family_id = row.get("family_id")
        if not isinstance(family_id, str) or not family_id or not family_id.isascii():
            raise ValueError("Family IDs must be non-empty ASCII strings")
        if row.get("status") not in STATUS:
            raise ValueError(f"{family_id}: invalid status")
        status_counts[row["status"]] += 1
        if row.get("gt_status") not in GT_STATUS:
            raise ValueError(f"{family_id}: invalid GT status")
        gt_counts[row["gt_status"]] += 1
        goal = row.get("pilot_sample_goal")
        if not isinstance(goal, int) or not 20 <= goal <= 30:
            raise ValueError(f"{family_id}: pilot_sample_goal must be 20-30")
        for required in ("label", "query_input", "output_target", "adapter", "verifier"):
            if not isinstance(row.get(required), str) or not row[required].strip():
                raise ValueError(f"{family_id}: missing {required}")
        artifacts = row.get("local_artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError(f"{family_id}: local_artifacts must be a list")
        for artifact in artifacts:
            if artifact.get("status") not in ARTIFACT_STATUS:
                raise ValueError(f"{family_id}: invalid artifact status")
            if "path" not in artifact:
                continue
            path = workspace_path(artifact["path"])
            if artifact["status"] == "available":
                checked_artifacts += 1
                if check_existing and not path.exists():
                    missing_artifacts.append(artifact["path"])
    if missing_artifacts:
        raise FileNotFoundError("Missing available artifacts: " + ", ".join(missing_artifacts))
    return {
        "families": len(families),
        "status_counts": dict(sorted(status_counts.items())),
        "gt_counts": dict(sorted(gt_counts.items())),
        "available_artifacts_checked": checked_artifacts,
    }


def summarize_kimi_runs(summary_paths: list[str | Path]) -> dict[str, Any]:
    """Summarize existing Kimi smoke files without starting a new model run."""
    rows: list[dict[str, Any]] = []
    for item in summary_paths:
        path = workspace_path(item)
        summary = json.loads(path.read_text(encoding="utf-8"))
        for run in summary.get("runs", []):
            rows.append({"path": str(path.relative_to(ROOT)), **run})
    attempted = len(rows)
    graded = [row for row in rows if row.get("status") == "graded"]
    passed = [row for row in graded if row.get("passed") is True]
    timeouts = [row for row in rows if row.get("timed_out") is True or row.get("status") == "timeout"]
    return {
        "attempted": attempted,
        "graded": len(graded),
        "passed": len(passed),
        "timeouts": len(timeouts),
        "pass_rate_attempted": None if not attempted else len(passed) / attempted,
        "pass_rate_graded": None if not graded else len(passed) / len(graded),
        "tasks": [{"task_id": row.get("task_id"), "status": row.get("status"),
                   "passed": row.get("passed"), "path": row["path"]} for row in rows],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", default="evals/posttrain/cad_data_families.json")
    parser.add_argument("--check-existing", action="store_true")
    parser.add_argument("--kimi-summary", action="append", default=[])
    args = parser.parse_args()
    registry = load_registry(args.registry)
    result = {"registry": validate_registry(registry, check_existing=args.check_existing)}
    if args.kimi_summary:
        result["kimi"] = summarize_kimi_runs(args.kimi_summary)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
