"""Run the durable agent kernel without requiring a model or AutoCAD."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import uuid

from cad_evoloop.agent import ProjectKernel, ProjectStore, WorkContext, WorkResult


class DemoExecutor:
    def execute(self, context: WorkContext) -> WorkResult:
        return WorkResult(
            outcome="succeeded",
            summary=f"Completed {context.unit['title']}",
            outputs=[{"uri": f"artifact://{context.project_id}/{context.unit['unit_id']}"}],
            evidence=[{"criterion": item, "passed": True} for item in context.unit["acceptance_criteria"]],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".local/agent-projects"))
    parser.add_argument("--project-id", default=f"demo-{uuid.uuid4().hex[:8]}")
    args = parser.parse_args()

    store = ProjectStore.create(
        args.root,
        args.project_id,
        "Reconstruct and verify a CAD part from supplied evidence",
        metadata={"example": True},
    )
    store.add_work_unit(
        unit_id="interpret",
        kind="demo",
        title="Interpret evidence",
        description="Extract geometry hypotheses and unresolved dimensions",
        acceptance_criteria=["Hypotheses are explicit", "Unknowns are recorded"],
    )
    store.add_work_unit(
        unit_id="model",
        kind="demo",
        title="Create geometry",
        description="Build a native CAD candidate",
        dependencies=["interpret"],
        acceptance_criteria=["Native artifact exists"],
    )
    store.add_work_unit(
        unit_id="verify",
        kind="demo",
        title="Verify candidate",
        description="Run deterministic and visual checks",
        dependencies=["model"],
        acceptance_criteria=["All required checks pass"],
    )

    results = ProjectKernel(store, {"demo": DemoExecutor()}).run()
    print(json.dumps({
        "project_dir": str(store.project_dir),
        "steps": [result.__dict__ for result in results],
        "state": store.load(),
        "integrity": store.verify(),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
