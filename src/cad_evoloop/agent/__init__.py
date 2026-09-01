"""Durable, model-neutral agent primitives."""

from .context import ContextView, build_context_view
from .artifacts import ArtifactRef
from .contracts import ArtifactRequirement, StageContract
from .kernel import ProjectKernel, StepResult, WorkContext, WorkResult, WorkUnitExecutor
from .operations import (
    OperationBroker,
    OperationCompensated,
    OperationNeedsReconciliation,
    ReconciliationResult,
)
from .planning import EngineeringPlan, WorkUnitSpec, apply_plan, standard_cae_plan
from .state import ready_work_units, replay
from .store import ProjectStore

__all__ = [
    "ArtifactRef",
    "ArtifactRequirement",
    "ContextView",
    "EngineeringPlan",
    "OperationBroker",
    "OperationCompensated",
    "OperationNeedsReconciliation",
    "ProjectKernel",
    "ProjectStore",
    "ReconciliationResult",
    "StepResult",
    "StageContract",
    "WorkUnitSpec",
    "WorkContext",
    "WorkResult",
    "WorkUnitExecutor",
    "apply_plan",
    "build_context_view",
    "ready_work_units",
    "replay",
    "standard_cae_plan",
]
