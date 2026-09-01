# EvoCAD Long-Horizon Agent Kernel

Status: first executable slice, 2026-09-01

## What Exists

`cad_evoloop.agent` is a model-neutral, durable project runtime. It does not
keep a project alive by preserving one model chat. Instead, it stores project
facts as hash-chained events and reconstructs the current state from them.

Each project has:

```text
<project-root>/<project-id>/
  events.jsonl       append-only source of truth
  state.json         disposable, atomically replaced snapshot
  artifacts/         project-level outputs and references
```

The first slice provides:

- a GoalGraph made of typed work units, dependencies, and acceptance criteria;
- deterministic state reduction and event replay;
- idempotent event submission and execution receipts;
- bounded attempts, pause/resume states, and explicit blocked/failed states;
- recovery of work that was running when the process stopped;
- provider-neutral model request, turn, capability, and conversation types;
- bounded context views derived from full history;
- hash-chain and snapshot-integrity verification.

## Why This Is Long-Horizon

A model conversation is temporary compute, not project memory. The project can
span processes, model providers, machines, and human review sessions because
the durable identity is the project and its artifacts. A conversation handle
belongs only to the local work unit that needs it.

The scheduler operates on bounded work units. A work unit is ready only when
all dependencies have succeeded. It transitions through append-only events:

```text
pending -> running -> succeeded
                   -> pending      (retry/interruption with budget left)
                   -> blocked
                   -> failed
```

`attempts` counts policy attempts. `execution_id` identifies one execution and
binds its result to its start event. Event idempotency prevents duplicate state
transitions and rejects reuse of a key with different content.

This does not provide exactly-once semantics for AutoCAD. A process may stop
after AutoCAD applies a command but before EvoCAD records its result. The CAD
integration therefore needs operation-level receipts plus reconciliation: on
resume, inspect the document/artifact to decide whether to adopt the prior
effect, compensate it, or execute again. The current slice detects the
interrupted work unit but does not yet implement that tool broker.

## Context Engineering

The complete event log is never copied wholesale into every model request.
`build_context_view` projects a bounded working set containing:

- immutable project goal and metadata;
- the focused work unit and its acceptance criteria;
- verified outputs from completed work;
- blocked or failed work and its evidence;
- a small recent-event window.

This view can be regenerated, so a lossy model summary never replaces source
facts. Later compaction and retrieval layers should also write derived artifacts
that link back to their source event ranges.

## Run The Slice

From the repository root:

```powershell
python -m pip install -e .
python examples/long_horizon_agent.py
python -m pytest tests/test_agent_kernel.py -q
```

The example deliberately uses a deterministic demo executor. It validates the
project runtime without spending model tokens or opening AutoCAD.

## Integration Boundary

The current geometry campaign remains unchanged. The next vertical slice is:

1. Wrap its Codex invocation in a compatibility `ModelProvider`.
2. Implement a direct API provider using the same EvoCAD request/turn types.
3. Wrap one geometry campaign attempt as a CAD `WorkUnitExecutor`.
4. Add MCP operation receipts and AutoCAD-state reconciliation.
5. Store the existing RunLedger run ID, checkpoint, verifier report, reflection,
   and MCP audit as work-unit outputs and evidence.
6. Replay a recorded campaign through the new kernel and require identical stop
   reasons and selected checkpoints before replacing the old loop.

This migration order separates semantic parity from new policy research. Once
parity is measured, context retrieval, branching, model routing, procedural
memory, and offline RSI can be introduced as individually testable ablations.
