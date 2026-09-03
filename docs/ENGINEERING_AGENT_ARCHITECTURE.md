# EvoCAD Engineering Project Agent

Status: executable foundation, 2026-09-02

## Scope

EvoCAD is evolving from a geometry-reconstruction loop into a durable agent for
requirements, CAD, analysis idealization, meshing, simulation, post-processing,
engineering assessment, and design optimization.

The project runtime is intentionally model-neutral. Codex CLI is the first
compatibility provider because it can reuse the existing authenticated runtime
and AutoCAD MCP integration. Provider thread IDs never become project IDs.

## Engineering State Model

The durable state consists of four connected graphs:

1. GoalGraph: plans, work units, dependencies, attempts, and execution IDs.
2. ArtifactGraph: immutable engineering artifacts and parent lineage.
3. ContractGraph: typed stage inputs, outputs, and required verifiers.
4. OperationGraph: side-effect receipts and reconciliation decisions.

The canonical seven-stage plan is:

```text
design evidence
  -> requirement model
  -> CAD model
  -> analysis model
  -> mesh model
  -> result field
  -> post-process result
  -> engineering report
```

Dependencies follow data producers, not merely the previous stage. For example,
the solver depends on both the analysis model and mesh; assessment depends on
both the requirement model and post-processed results.

## Typed Artifact Contract

An artifact records a project-relative URI, SHA-256 digest, byte count, media
type, engineering kind, producing work unit, parents, and metadata. Files are
copied into content-addressed project storage. Project integrity verification
checks the event chain, state snapshot, file presence, size, and content hash.

A contract-bound work unit can succeed only when:

```text
required input artifact counts are satisfied
AND required output artifact counts are satisfied
AND every declared verifier reports pass
AND the gate belongs to the active execution ID
```

This prevents an LLM statement such as "the mesh is complete" from advancing
the workflow without a registered mesh and passing quality evidence.

## External Operation Semantics

CAD and solver calls cannot generally provide exactly-once execution. If the
caller stops after the external system applies an operation but before recording
the response, the effect is uncertain. EvoCAD records a request digest before
execution and requires one of three reconciliation dispositions after recovery:

- adopt: verified external state already contains the intended result;
- compensate: remove or supersede the partial effect;
- retry: verification shows the effect was not committed.

No generic timeout handler may silently retry an uncertain side effect.

## 2026 Research Alignment

The architecture follows findings visible across 2026 CAE-agent work:

- The WCCM-ECCOMAS CAD-FEA-optimization workflow uses state-aware targeted
  regeneration across FreeCAD, Gmsh, and PyMAPDL.
- ALL-FEM combines domain adaptation with execution feedback across 39 FEniCS
  solid, fluid, and multiphysics tasks.
- Scientific Reports separates LLM interpretation from deterministic numerical
  execution and explicit engineering verification.
- Self-Improving CAD Generation Agents demonstrate that visual plausibility is
  insufficient and that FEA feedback exposes failures missed by geometry-only
  generation.
- The 2026 CAD-to-mesh survey identifies topology checks, mesh-quality checks,
  and workflow integration as unresolved deployment requirements.
- ICLR 2026 long-horizon results show per-step reliability degradation and
  self-conditioning on prior errors, motivating bounded work units and gates.

Primary links are recorded in `docs/AGENT_ARCHITECTURE_RESEARCH.md`.

## Current Boundary

`durable-kernel-checkpoint-v2` wraps the feedback-bound geometry loop as one
contract-bound work unit and adds process-independent execution plus inner-loop
stage recovery. A workspace-local detached runner owns the batch process. Each
geometry job atomically records `action_running`, `action_completed`, and
`verifier_completed`; recovery reuses the same attempt and Codex thread while
preserving interrupted action and decision traces. This validates provider
isolation, project recovery, artifact lineage, contract gating, and campaign
reproducibility. It does not yet claim a better geometry policy because planning
and diagnosis remain inside the geometry loop.

The next behavioral condition will move one attempt, verification, diagnosis,
and replan decision into separate durable work units while preserving the same
Codex model and frozen samples.
