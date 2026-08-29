"""Evidence-qualified metrics that penalize unverified rubric weight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


CHECK_GROUPS = ("hard_gates", "dimensions", "rubrics")


def _weight(check: dict[str, Any]) -> float:
    value = check.get("weight", check.get("points", 1.0))
    weight = float(value)
    if weight <= 0:
        raise ValueError(f"Check weight must be positive: {check.get('id')}")
    return weight


def _visual_resolutions(visual: dict[str, Any] | None) -> dict[str, str]:
    if not visual:
        return {}
    combined = visual.get("combined", visual)
    resolutions: dict[str, str] = {}
    for item in combined.get("resolved", []):
        if not item.get("accepted", True):
            continue
        identifier = str(item.get("id", ""))
        verdict = item.get("verdict")
        if identifier and verdict in {"pass", "fail"}:
            if identifier in resolutions:
                raise ValueError(f"Duplicate visual resolution: {identifier}")
            resolutions[identifier] = verdict
    return resolutions


def evidence_qualified_completion(
    deterministic: dict[str, Any],
    visual: dict[str, Any] | None = None,
    *,
    success_threshold: float = 100.0,
) -> dict[str, Any]:
    """Compute completion from check-level evidence instead of nominal score."""
    if not 0.0 <= success_threshold <= 100.0:
        raise ValueError("success_threshold must be between 0 and 100")
    resolutions = _visual_resolutions(visual)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for group in CHECK_GROUPS:
        for check in deterministic.get(group, []):
            identifier = str(check.get("id", ""))
            if not identifier:
                raise ValueError(f"Missing check id in {group}")
            if identifier in seen:
                raise ValueError(f"Duplicate check id: {identifier}")
            seen.add(identifier)
            original = check.get("status", "unverified")
            status = resolutions.get(identifier, original)
            if status not in {"pass", "fail", "unverified"}:
                raise ValueError(f"Unsupported check status for {identifier}: {status}")
            rows.append({
                "id": identifier,
                "group": group,
                "weight": _weight(check),
                "status": status,
                "evidence_source": "visual" if identifier in resolutions else "deterministic",
            })

    unknown_resolutions = sorted(set(resolutions) - seen)
    if unknown_resolutions:
        raise ValueError(f"Visual verdict resolved unknown check ids: {unknown_resolutions}")

    total = sum(item["weight"] for item in rows)
    passed = sum(item["weight"] for item in rows if item["status"] == "pass")
    failed = sum(item["weight"] for item in rows if item["status"] == "fail")
    unresolved = sum(item["weight"] for item in rows if item["status"] == "unverified")
    verified = passed + failed
    eqc = 0.0 if total == 0 else 100.0 * passed / total
    coverage = 0.0 if total == 0 else 100.0 * verified / total
    conditional = 0.0 if verified == 0 else 100.0 * passed / verified
    hard_gate_failed = any(
        item["group"] == "hard_gates" and item["status"] != "pass" for item in rows
    )
    return {
        "schema_version": "1.0",
        "eqc": round(eqc, 2),
        "coverage": round(coverage, 2),
        "conditional_accuracy": round(conditional, 2),
        "success_threshold": success_threshold,
        "success": total > 0 and eqc >= success_threshold and not hard_gate_failed,
        "hard_gate_failed": hard_gate_failed,
        "weights": {
            "total": round(total, 6),
            "passed": round(passed, 6),
            "failed": round(failed, 6),
            "unresolved": round(unresolved, 6),
        },
        "checks": rows,
    }


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--visual-verdict", type=Path)
    parser.add_argument("--success-threshold", type=float, default=100.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    deterministic = json.loads(args.verdict.read_text(encoding="utf-8"))
    visual = (
        json.loads(args.visual_verdict.read_text(encoding="utf-8"))
        if args.visual_verdict else None
    )
    result = evidence_qualified_completion(
        deterministic, visual, success_threshold=args.success_threshold,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
