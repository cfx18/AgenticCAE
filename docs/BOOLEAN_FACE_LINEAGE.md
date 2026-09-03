# Boolean Face Lineage

Status: implemented prototype, 2026-09-03

## Purpose

Native feature localization answers where a candidate differs from the hidden
evaluation solid. Boolean face lineage adds a conservative answer to a separate
question: which modeling job and declared operation may have created or changed
the implicated candidate face?

The protocol does not restrict AutoLISP, AutoCAD commands, construction order,
or geometry type. It observes topology before and after an unrestricted Core
Console job.

Protocol identifier: `evocad-boolean-face-lineage-v2`.

## Capture

For each `autocad_core_start` job, the audited MCP wrapper:

1. opens the requested input DWG in an isolated Core Console process;
2. exports `topology-before.json` through the managed BRep plugin;
3. executes the Agent's unchanged AutoLISP payload;
4. exports `topology-after.json` from the resulting drawing;
5. records both snapshot paths, the MCP job ID, input and output paths, and the
   Agent-declared operation manifest in the immutable audit response.

Topology capture is diagnostic. If the managed exporter is unavailable, the
CAD job can still succeed and the capture status becomes `unavailable` or
`partial`.

## Face matching

Each native face fingerprint binds its analytic surface descriptor, area,
bounds, and loop signature. For current face `f` and parent face set `P`:

```text
inherited(f) = exists p in P such that fingerprint(f) = fingerprint(p)
```

An exact unique fingerprint match is high-confidence inheritance. A face with
no stable parent fingerprint is classified as `created_or_modified`. Parent
faces not retained after the operation are classified collectively as
`deleted_or_modified`.

Version 2 propagates the originating operation through every captured job in a
branched attempt. It keys each stage by its input and output DWG paths, carries
stable face fingerprints along that path, and assigns a changed face to the
geometry-changing operations in the stage where its fingerprint first appears.
Validation-only operations are excluded from geometric causality.

This intentionally does not claim that geometrically similar faces are the same
topological face.

## Operation attribution

Operation manifests may record:

- `operation_id` and `intent`;
- `operation_type`, such as primitive, union, subtract, intersect, fillet, or
  recovery;
- semantic `feature_id`;
- editable `parameters`;
- `parent_operation_ids`;
- known target entity handles or face fingerprints.

Attribution confidence is:

- high when an operation declares the exact output face fingerprint;
- medium when a topology-delta face belongs to a job with one candidate
  operation;
- low when several operations share one job or only a final entity handle is
  available.

When several operations execute in one job, EvoCAD reports an operation group.
It does not invent a unique responsible operation. Agents are encouraged, but
not required, to isolate major feature-changing Booleans in recoverable jobs.

## Verifier feedback

Localized mismatch regions retain their ranked `candidate_topology_faces`.
Each matched face now includes `boolean_lineage`. The corresponding
`responsible_operation_candidates` include operation type, feature ID, editable
parameters, parent operation IDs, evidence, and confidence.

This changes feedback from:

```text
region -> nearby final solid handle -> several operations
```

to:

```text
region -> native face -> inherited or changed in this job
       -> candidate operation -> feature parameters
```

The final arrow is exact only when the operation manifest or job isolation
supports it.

## Real AutoCAD validation

Two isolated AutoCAD 2024 Core Console checks passed on 2026-09-03:

1. A 10 mm box produced 0 parent faces and 6 new faces, all assigned to the
   single `base-box` operation.
2. Subtracting a diameter-4 through hole from that box produced 7 final faces:
   4 inherited side faces and 3 created-or-modified faces. The two modified end
   faces and new cylindrical hole wall were assigned to the single
   `through-hole` operation with parameters `diameter=4` and `depth=10`.

## Evaluation boundary

The completed `agent-geometry-30-sol-native-feedback-v3` campaign remains bound
to `durable-kernel-checkpoint-v2`. Boolean lineage begins a new condition,
`durable-kernel-boolean-lineage-v4`. Results from the two conditions must not be
pooled without reporting the intervention.

## Pilot findings

The two-sample V2 pilot confirmed that fingerprint propagation can identify an
inherited face from an earlier modeling stage and prevent validation-only jobs
from receiving geometric blame. During the ortho2cad recovery replicate, the
Agent used this evidence to preserve implicated inherited faces, reject
regressed parameter sets, and run increasingly narrow parameter experiments.

Two attribution limits became concrete:

1. Several declared operations inside one Core Console job remain an operation
   group. The protocol cannot infer an exact within-script Boolean boundary.
2. A near-pass can have zero localized regions under the fixed distance
   threshold. In that case the face lineage is present, but no residual region
   exists to connect to it.

The next instrumentation candidate is an optional intra-job lineage checkpoint
that records an operation boundary without constraining which AutoCAD or
AutoLISP geometry commands may execute. Adaptive near-pass localization and
resumption after a safety-censored final reflection should be evaluated
separately so their effects are not conflated with lineage.
