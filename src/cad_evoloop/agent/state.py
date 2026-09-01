"""Pure project-state reducer for the long-horizon agent kernel."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from cad_evoloop.agent.contracts import requirements_satisfied
from cad_evoloop.agent.artifacts import ArtifactRef


PROJECT_STATUSES = {"active", "paused", "completed", "failed", "cancelled"}
WORK_STATUSES = {"pending", "running", "blocked", "succeeded", "failed", "cancelled"}
TERMINAL_PROJECT_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_WORK_STATUSES = {"succeeded", "failed", "cancelled"}


def empty_state(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "goal": None,
        "status": None,
        "metadata": {},
        "artifacts": {},
        "artifact_order": [],
        "contracts": {},
        "contract_order": [],
        "contract_evaluations": {},
        "operations": {},
        "operation_order": [],
        "plans": {},
        "plan_order": [],
        "work_units": {},
        "work_order": [],
        "last_sequence": 0,
        "last_event_hash": None,
        "created_at": None,
        "updated_at": None,
        "completion_summary": None,
    }


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _work_unit(state: dict[str, Any], unit_id: Any) -> dict[str, Any]:
    unit_id = _required_text(unit_id, "unit_id")
    try:
        return state["work_units"][unit_id]
    except KeyError as exc:
        raise ValueError(f"Unknown work unit: {unit_id}") from exc


def _require_project_active(state: dict[str, Any]) -> None:
    if state["status"] != "active":
        raise ValueError(f"Project must be active, found {state['status']!r}")


def _artifact_kinds(state: dict[str, Any], artifact_ids: Iterable[str]) -> list[str]:
    return [state["artifacts"][artifact_id]["kind"] for artifact_id in artifact_ids]


def _unit_input_artifact_ids(state: dict[str, Any], unit: dict[str, Any]) -> list[str]:
    values = list(unit["input_artifact_ids"])
    for artifact_id in state["artifact_order"]:
        artifact = state["artifacts"][artifact_id]
        if artifact["producer_work_unit"] in unit["dependencies"] and artifact_id not in values:
            values.append(artifact_id)
    return values


def _contract_inputs_satisfied(state: dict[str, Any], unit: dict[str, Any]) -> bool:
    if unit["contract_id"] is None:
        return True
    contract = state["contracts"][unit["contract_id"]]
    return requirements_satisfied(
        contract["input_requirements"],
        _artifact_kinds(state, _unit_input_artifact_ids(state, unit)),
    )


def _validate_dependencies(state: dict[str, Any], unit_id: str, dependencies: Any) -> list[str]:
    if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
        raise ValueError("dependencies must be an array of work-unit identifiers")
    if len(dependencies) != len(set(dependencies)):
        raise ValueError("dependencies must not contain duplicates")
    if unit_id in dependencies:
        raise ValueError("A work unit cannot depend on itself")
    unknown = [item for item in dependencies if item not in state["work_units"]]
    if unknown:
        raise ValueError(f"Work-unit dependencies must already exist: {unknown}")
    return dependencies


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    payload = event["payload"]
    event_type = event["event_type"]

    if event_type == "project.created":
        if next_state["status"] is not None:
            raise ValueError("Project has already been created")
        next_state["goal"] = _required_text(payload.get("goal"), "goal")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("project metadata must be an object")
        next_state["metadata"] = metadata
        next_state["status"] = "active"
        next_state["created_at"] = event["occurred_at"]

    elif event_type == "project.paused":
        _require_project_active(next_state)
        next_state["status"] = "paused"

    elif event_type == "project.resumed":
        if next_state["status"] != "paused":
            raise ValueError("Only a paused project can resume")
        next_state["status"] = "active"

    elif event_type in {"project.completed", "project.failed", "project.cancelled"}:
        if next_state["status"] in TERMINAL_PROJECT_STATUSES:
            raise ValueError("Project is already terminal")
        target = event_type.split(".", 1)[1]
        if target == "completed" and any(
            unit["status"] != "succeeded" for unit in next_state["work_units"].values()
        ):
            raise ValueError("Project cannot complete before every work unit succeeds")
        next_state["status"] = target
        next_state["completion_summary"] = payload.get("summary")

    elif event_type == "plan.registered":
        _require_project_active(next_state)
        plan_id = _required_text(payload.get("plan_id"), "plan_id")
        if plan_id in next_state["plans"]:
            raise ValueError(f"Duplicate engineering plan: {plan_id}")
        parent = payload.get("parent_plan_id")
        if parent is not None and parent not in next_state["plans"]:
            raise ValueError(f"Unknown parent engineering plan: {parent}")
        work_units = payload.get("work_units")
        if not isinstance(work_units, list) or not work_units:
            raise ValueError("Engineering plan must declare work units")
        next_state["plans"][plan_id] = {**deepcopy(payload), "registered_at": event["occurred_at"]}
        next_state["plan_order"].append(plan_id)

    elif event_type == "operation.started":
        _require_project_active(next_state)
        operation_id = _required_text(payload.get("operation_id"), "operation_id")
        if operation_id in next_state["operations"]:
            raise ValueError(f"Duplicate operation: {operation_id}")
        unit = _work_unit(next_state, payload.get("work_unit_id"))
        if unit["status"] != "running" or payload.get("execution_id") != unit["active_execution_id"]:
            raise ValueError("An operation must belong to the active work-unit execution")
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("Operation arguments must be an object")
        next_state["operations"][operation_id] = {
            **deepcopy(payload),
            "status": "running",
            "attempts": 1,
            "result": None,
            "artifact_ids": [],
            "last_error": None,
            "reconciliation_summary": None,
            "started_at": event["occurred_at"],
            "updated_at": event["occurred_at"],
        }
        next_state["operation_order"].append(operation_id)

    elif event_type == "operation.retry_started":
        _require_project_active(next_state)
        operation_id = _required_text(payload.get("operation_id"), "operation_id")
        operation = next_state["operations"].get(operation_id)
        if operation is None or operation["status"] != "retryable":
            raise ValueError("Only a retryable operation can start another attempt")
        unit = _work_unit(next_state, payload.get("work_unit_id"))
        if unit["status"] != "running" or payload.get("execution_id") != unit["active_execution_id"]:
            raise ValueError("An operation retry must belong to the active work-unit execution")
        operation["work_unit_id"] = unit["unit_id"]
        operation["execution_id"] = payload["execution_id"]
        operation["status"] = "running"
        operation["attempts"] += 1
        operation["last_error"] = None
        operation["updated_at"] = event["occurred_at"]

    elif event_type in {"operation.completed", "operation.uncertain"}:
        _require_project_active(next_state)
        operation_id = _required_text(payload.get("operation_id"), "operation_id")
        operation = next_state["operations"].get(operation_id)
        if operation is None or operation["status"] != "running":
            raise ValueError("Operation does not have an active attempt")
        if event_type == "operation.completed":
            result = payload.get("result")
            artifact_ids = payload.get("artifact_ids", [])
            if not isinstance(result, dict) or not isinstance(artifact_ids, list):
                raise ValueError("Completed operation result must be an object with artifact IDs")
            unknown = [item for item in artifact_ids if item not in next_state["artifacts"]]
            if unknown:
                raise ValueError(f"Unknown operation artifacts: {unknown}")
            operation["status"] = "completed"
            operation["result"] = result
            operation["artifact_ids"] = artifact_ids
        else:
            operation["status"] = "uncertain"
            operation["last_error"] = payload.get("error")
        operation["updated_at"] = event["occurred_at"]

    elif event_type == "operation.reconciled":
        _require_project_active(next_state)
        operation_id = _required_text(payload.get("operation_id"), "operation_id")
        operation = next_state["operations"].get(operation_id)
        if operation is None or operation["status"] != "uncertain":
            raise ValueError("Only an uncertain operation can be reconciled")
        disposition = payload.get("disposition")
        if disposition not in {"adopt", "compensate", "retry"}:
            raise ValueError("Operation reconciliation must adopt, compensate, or retry")
        operation["reconciliation_summary"] = _required_text(payload.get("summary"), "summary")
        if disposition == "adopt":
            result = payload.get("result")
            artifact_ids = payload.get("artifact_ids", [])
            if not isinstance(result, dict) or not isinstance(artifact_ids, list):
                raise ValueError("Adopted operation requires a result and artifact IDs")
            unknown = [item for item in artifact_ids if item not in next_state["artifacts"]]
            if unknown:
                raise ValueError(f"Unknown adopted artifacts: {unknown}")
            operation["status"] = "completed"
            operation["result"] = result
            operation["artifact_ids"] = artifact_ids
        elif disposition == "compensate":
            operation["status"] = "compensated"
        else:
            operation["status"] = "retryable"
        operation["updated_at"] = event["occurred_at"]

    elif event_type == "contract.registered":
        _require_project_active(next_state)
        contract_id = _required_text(payload.get("contract_id"), "contract_id")
        if contract_id in next_state["contracts"]:
            raise ValueError(f"Duplicate stage contract: {contract_id}")
        input_requirements = payload.get("input_requirements", [])
        output_requirements = payload.get("output_requirements", [])
        verifier_ids = payload.get("verifier_ids", [])
        if not isinstance(input_requirements, list) or not isinstance(output_requirements, list):
            raise ValueError("Stage contract requirements must be arrays")
        if not output_requirements or not isinstance(verifier_ids, list) or not verifier_ids:
            raise ValueError("Stage contract requires outputs and verifiers")
        for requirements in (input_requirements, output_requirements):
            kinds = []
            for item in requirements:
                if not isinstance(item, dict):
                    raise ValueError("Artifact requirements must be objects")
                kind = _required_text(item.get("kind"), "artifact requirement kind")
                count = item.get("min_count", 1)
                if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                    raise ValueError("Artifact requirement min_count must be positive")
                kinds.append(kind)
            if len(kinds) != len(set(kinds)):
                raise ValueError("Artifact requirement kinds must be unique")
        if any(not isinstance(item, str) or not item.strip() for item in verifier_ids):
            raise ValueError("Stage contract verifier identifiers must be non-empty")
        if len(verifier_ids) != len(set(verifier_ids)):
            raise ValueError("Stage contract verifier identifiers must be unique")
        next_state["contracts"][contract_id] = deepcopy(payload)
        next_state["contract_order"].append(contract_id)

    elif event_type == "artifact.registered":
        _require_project_active(next_state)
        artifact_id = _required_text(payload.get("artifact_id"), "artifact_id")
        if artifact_id in next_state["artifacts"]:
            raise ValueError(f"Duplicate artifact: {artifact_id}")
        producer = payload.get("producer_work_unit")
        if producer is not None:
            producer = _work_unit(next_state, producer)["unit_id"]
        parents = payload.get("parents", [])
        if not isinstance(parents, list) or len(parents) != len(set(parents)):
            raise ValueError("Artifact parents must be a duplicate-free array")
        unknown = [item for item in parents if item not in next_state["artifacts"]]
        if unknown:
            raise ValueError(f"Artifact parents must already exist: {unknown}")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Artifact metadata must be an object")
        uri = _required_text(payload.get("uri"), "artifact uri")
        uri_parts = uri.replace("\\", "/").split("/")
        if uri.startswith(("/", "\\")) or ".." in uri_parts:
            raise ValueError("Artifact URI must be a project-relative path")
        validated = ArtifactRef(
            artifact_id=artifact_id,
            kind=_required_text(payload.get("kind"), "artifact kind"),
            uri=uri,
            sha256=payload.get("sha256"),
            byte_size=payload.get("byte_size"),
            media_type=_required_text(payload.get("media_type"), "artifact media_type"),
            producer_work_unit=producer,
            parents=tuple(parents),
            metadata=metadata,
        ).to_dict()
        next_state["artifacts"][artifact_id] = {
            **validated,
            "producer_work_unit": producer,
            "registered_at": event["occurred_at"],
        }
        next_state["artifact_order"].append(artifact_id)
        if producer is not None:
            next_state["work_units"][producer]["artifact_ids"].append(artifact_id)

    elif event_type == "contract.evaluated":
        _require_project_active(next_state)
        evaluation_id = _required_text(payload.get("evaluation_id"), "evaluation_id")
        if evaluation_id in next_state["contract_evaluations"]:
            raise ValueError(f"Duplicate contract evaluation: {evaluation_id}")
        unit = _work_unit(next_state, payload.get("work_unit_id"))
        contract_id = _required_text(payload.get("contract_id"), "contract_id")
        if contract_id != unit["contract_id"] or contract_id not in next_state["contracts"]:
            raise ValueError("Contract evaluation does not match the work unit")
        if unit["status"] != "running" or payload.get("execution_id") != unit["active_execution_id"]:
            raise ValueError("Contract evaluation requires the active work-unit execution")
        contract = next_state["contracts"][contract_id]
        checks = payload.get("checks")
        if not isinstance(checks, list):
            raise ValueError("Contract evaluation checks must be an array")
        check_map = {}
        for check in checks:
            if not isinstance(check, dict):
                raise ValueError("Contract evaluation checks must be objects")
            verifier_id = _required_text(check.get("verifier_id"), "verifier_id")
            if verifier_id in check_map:
                raise ValueError("Contract evaluation verifier identifiers must be unique")
            if check.get("status") not in {"pass", "fail", "unverified"}:
                raise ValueError("Contract check status must be pass, fail, or unverified")
            check_map[verifier_id] = check
        if set(check_map) != set(contract["verifier_ids"]):
            raise ValueError("Contract evaluation must cover exactly the declared verifiers")
        input_ids = _unit_input_artifact_ids(next_state, unit)
        output_ids = list(unit["artifact_ids"])
        inputs_ok = requirements_satisfied(
            contract["input_requirements"], _artifact_kinds(next_state, input_ids),
        )
        outputs_ok = requirements_satisfied(
            contract["output_requirements"], _artifact_kinds(next_state, output_ids),
        )
        passed = inputs_ok and outputs_ok and all(
            check["status"] == "pass" for check in check_map.values()
        )
        evaluation = {
            **deepcopy(payload),
            "input_artifact_ids": input_ids,
            "output_artifact_ids": output_ids,
            "inputs_satisfied": inputs_ok,
            "outputs_satisfied": outputs_ok,
            "passed": passed,
            "evaluated_at": event["occurred_at"],
        }
        next_state["contract_evaluations"][evaluation_id] = evaluation
        unit["latest_contract_evaluation_id"] = evaluation_id

    elif event_type == "work_unit.added":
        _require_project_active(next_state)
        unit_id = _required_text(payload.get("unit_id"), "unit_id")
        if unit_id in next_state["work_units"]:
            raise ValueError(f"Duplicate work unit: {unit_id}")
        dependencies = _validate_dependencies(next_state, unit_id, payload.get("dependencies", []))
        acceptance = payload.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance or any(
            not isinstance(item, str) or not item.strip() for item in acceptance
        ):
            raise ValueError("acceptance_criteria must contain at least one non-empty string")
        max_attempts = payload.get("max_attempts", 3)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        contract_id = payload.get("contract_id")
        if contract_id is not None and contract_id not in next_state["contracts"]:
            raise ValueError(f"Unknown stage contract: {contract_id}")
        plan_id = payload.get("plan_id")
        if plan_id is not None and plan_id not in next_state["plans"]:
            raise ValueError(f"Unknown engineering plan: {plan_id}")
        input_artifact_ids = payload.get("input_artifact_ids", [])
        if not isinstance(input_artifact_ids, list) or len(input_artifact_ids) != len(set(input_artifact_ids)):
            raise ValueError("input_artifact_ids must be a duplicate-free array")
        missing_inputs = [
            artifact_id for artifact_id in input_artifact_ids
            if artifact_id not in next_state["artifacts"]
        ]
        if missing_inputs:
            raise ValueError(f"Unknown input artifacts: {missing_inputs}")
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Work-unit parameters must be an object")
        next_state["work_units"][unit_id] = {
            "unit_id": unit_id,
            "kind": _required_text(payload.get("kind", "generic"), "kind"),
            "title": _required_text(payload.get("title"), "title"),
            "description": _required_text(payload.get("description"), "description"),
            "dependencies": dependencies,
            "acceptance_criteria": [item.strip() for item in acceptance],
            "phase": _required_text(payload.get("phase", "execution"), "phase"),
            "contract_id": contract_id,
            "plan_id": plan_id,
            "input_artifact_ids": input_artifact_ids,
            "artifact_ids": [],
            "latest_contract_evaluation_id": None,
            "parameters": parameters,
            "max_attempts": max_attempts,
            "status": "pending",
            "attempts": 0,
            "active_execution_id": None,
            "last_error": None,
            "summary": None,
            "outputs": [],
            "evidence": [],
            "added_at": event["occurred_at"],
            "updated_at": event["occurred_at"],
        }
        next_state["work_order"].append(unit_id)

    elif event_type == "work_unit.started":
        _require_project_active(next_state)
        unit = _work_unit(next_state, payload.get("unit_id"))
        if unit["status"] != "pending":
            raise ValueError(f"Work unit {unit['unit_id']} is not pending")
        unsatisfied = [
            item for item in unit["dependencies"]
            if next_state["work_units"][item]["status"] != "succeeded"
        ]
        if unsatisfied:
            raise ValueError(f"Work unit dependencies are not satisfied: {unsatisfied}")
        if not _contract_inputs_satisfied(next_state, unit):
            raise ValueError(f"Stage contract inputs are not satisfied for {unit['unit_id']}")
        if unit["attempts"] >= unit["max_attempts"]:
            raise ValueError(f"Work unit {unit['unit_id']} exhausted its attempts")
        execution_id = _required_text(payload.get("execution_id"), "execution_id")
        unit["status"] = "running"
        unit["attempts"] += 1
        unit["active_execution_id"] = execution_id
        unit["updated_at"] = event["occurred_at"]

    elif event_type in {
        "work_unit.succeeded", "work_unit.retry_scheduled", "work_unit.blocked",
        "work_unit.failed", "work_unit.cancelled", "work_unit.interrupted",
    }:
        unit = _work_unit(next_state, payload.get("unit_id"))
        execution_id = payload.get("execution_id")
        if unit["status"] != "running":
            raise ValueError(f"Work unit {unit['unit_id']} is not running")
        if execution_id != unit["active_execution_id"]:
            raise ValueError(f"Execution receipt does not match work unit {unit['unit_id']}")
        outcome = event_type.split(".", 1)[1]
        if outcome == "succeeded" and unit["contract_id"] is not None:
            evaluation_id = unit["latest_contract_evaluation_id"]
            evaluation = next_state["contract_evaluations"].get(evaluation_id)
            if not evaluation or not evaluation["passed"]:
                raise ValueError("A contract-bound work unit cannot succeed without a passing gate")
            if evaluation["execution_id"] != execution_id:
                raise ValueError("Contract evaluation belongs to a different execution")
        if outcome in {"retry_scheduled", "interrupted"}:
            if unit["attempts"] >= unit["max_attempts"]:
                unit["status"] = "failed"
            else:
                unit["status"] = "pending"
        else:
            unit["status"] = outcome
        unit["active_execution_id"] = None
        unit["last_error"] = payload.get("error")
        unit["summary"] = payload.get("summary") or unit["summary"]
        outputs = payload.get("outputs", [])
        evidence = payload.get("evidence", [])
        if not isinstance(outputs, list) or not isinstance(evidence, list):
            raise ValueError("Work-unit outputs and evidence must be arrays")
        if outputs:
            unit["outputs"] = outputs
        if evidence:
            unit["evidence"] = evidence
        unit["updated_at"] = event["occurred_at"]

    elif event_type == "work_unit.reopened":
        _require_project_active(next_state)
        unit = _work_unit(next_state, payload.get("unit_id"))
        if unit["status"] not in {"blocked", "failed", "cancelled"}:
            raise ValueError(f"Work unit {unit['unit_id']} cannot be reopened from {unit['status']}")
        if unit["attempts"] >= unit["max_attempts"]:
            additional_attempts = payload.get("additional_attempts", 0)
            if (
                isinstance(additional_attempts, bool)
                or not isinstance(additional_attempts, int)
                or additional_attempts < 1
            ):
                raise ValueError("Reopening an exhausted unit requires additional_attempts")
            unit["max_attempts"] += additional_attempts
        unit["status"] = "pending"
        unit["last_error"] = None
        unit["latest_contract_evaluation_id"] = None
        unit["updated_at"] = event["occurred_at"]

    else:
        raise ValueError(f"Unsupported project event type: {event_type}")

    if next_state["status"] not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status: {next_state['status']!r}")
    if any(unit["status"] not in WORK_STATUSES for unit in next_state["work_units"].values()):
        raise ValueError("Invalid work-unit status")
    next_state["last_sequence"] = event["sequence"]
    next_state["last_event_hash"] = event["event_hash"]
    next_state["updated_at"] = event["occurred_at"]
    return next_state


def replay(project_id: str, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    state = empty_state(project_id)
    for event in events:
        state = apply_event(state, event)
    return state


def ready_work_units(state: dict[str, Any]) -> list[dict[str, Any]]:
    if state["status"] != "active":
        return []
    return [
        state["work_units"][unit_id]
        for unit_id in state["work_order"]
        if state["work_units"][unit_id]["status"] == "pending"
        and all(
            state["work_units"][dependency]["status"] == "succeeded"
            for dependency in state["work_units"][unit_id]["dependencies"]
        )
        and _contract_inputs_satisfied(state, state["work_units"][unit_id])
    ]
