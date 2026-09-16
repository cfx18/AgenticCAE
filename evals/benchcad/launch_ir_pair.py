"""Launch the authorized IR campaigns from a process independent of the terminal."""

import json
from pathlib import Path
import sys
import time

from cad_evoloop.evaluation.detached_campaign import (
    campaign_runner_status,
    start_detached_campaign,
)


def main():
    root = Path(__file__).resolve().parents[2]
    outcomes = []
    for name, mode in (
        ("sol-family-30-baseline-v1", "baseline"),
        ("sol-family-30-specialist-v1", "specialist_ir"),
    ):
        state = campaign_runner_status(name)
        if state.get("alive"):
            outcomes.append(state)
            continue
        summary = root / "reports/generated/benchcad" / name / "summary.json"
        if summary.is_file():
            data = json.loads(summary.read_text(encoding="utf-8"))
            if data.get("records") == 30:
                outcomes.append({"campaign": name, "status": "already_finished"})
                continue
        try:
            outcomes.append(start_detached_campaign(name, [
                sys.executable, "-m", "cad_evoloop.evaluation.benchcad_supervisor",
                "--campaign", name, "--mode", mode,
            ]))
        except Exception as exc:
            outcomes.append({"campaign": name, "status": "launch_failed", "error": repr(exc)})
    log = root / "reports/generated/benchcad" / f"parallel-launch-{time.time_ns()}.json"
    log.write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
