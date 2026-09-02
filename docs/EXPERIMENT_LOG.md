# EvoCAD Experiment Log

## 2026-09-02: Surface-level feature localization foundation

The geometry verifier now emits deterministic bidirectional point-to-triangle
surface mismatch
regions under `evocad-surface-localization-v1`. Each region records its aligned
world-space centroid and bounds, normalized bounding-box position, area proxy,
distance severity, normal disagreement, and possible opposite-direction
counterparts. The result distinguishes missing-or-displaced from
excess-or-displaced evidence without claiming an unsupported CAD feature type.

Review exports materialize a separate hash-bound localization asset containing
bounded point samples. The synchronized Three.js views render the samples and
region boxes, and a reviewer can focus all views on any reported region.
Ground-truth STEP triangles retain stable B-Rep face fingerprints and analytic
surface types, so missing regions can cite the contributing plane, cylinder,
cone, sphere, or torus faces. Candidate-side native face identity, semantic
feature recognition, and CAD-operation provenance remain explicit later phases
rather than being inferred from triangle proximity.

The localization distance threshold is 0.006 of the ground-truth bounding-box
diagonal. An initial 0.003 threshold produced five tiny regions on one of ten
equivalent STEP/STL calibration pairs because of curved-surface tessellation;
the calibrated threshold sits above the observed 0.005714 maximum while still
exposing missing and excess engineering-scale geometry.

## 2026-09-02: Long-Horizon Engineering Foundation

Objective:

- support future CAD, analysis-model, mesh, solver, post-processing, assessment,
  and optimization tasks under one durable project identity;
- use Codex CLI initially and defer paid provider APIs;
- compare Agent architectures with `gpt-5.6-sol` fixed;
- run a frozen 30-sample evaluation before requesting human review.

Implemented condition: `durable-kernel-compat-v1`.

Implemented mechanisms:

- typed content-addressed artifacts with parent lineage;
- stage contracts and execution-bound verifier gates;
- versioned hierarchical engineering plans;
- operation receipts with adopt/compensate/retry reconciliation;
- model-neutral provider contracts and Codex CLI adapter;
- compatibility WorkUnit executor for the existing geometry v2 loop;
- one isolated durable Project per evaluation sample.

Frozen evaluation:

- selection: `evals/geometry-benchmarks/splits/geometry-30-devval-v1.json`;
- selection digest: `ac9bfc4f89426c4c764ea735c42a64aa1fc75a6f584e6cf4e46712221675f03a`;
- source: all 20 dev plus all 10 validation samples;
- hidden test samples used: zero;
- model: `gpt-5.6-sol`, medium reasoning;
- campaign: `agent-geometry-30-sol-v1`;
- protocol: `evocad-agent-geometry-v1`;
- sample isolation: one project per sample;
- strict verifier: geometry protocol v2.

Interpretation guardrail:

This condition changes durability and observability, not the inner modeling
policy. Its first evaluation is a semantic-parity and infrastructure study. A
future result must not report it as an Agent-quality gain over v2. Behavioral
Agent comparisons begin after planner and diagnosis are extracted into durable
work units and rerun on the same frozen selection with the same sol model.

Test checkpoint before campaign freeze: `174 passed, 3 skipped`.

Provider smoke:

- Codex CLI version: `0.150.0-alpha.12.2`;
- model: `gpt-5.6-sol`, medium reasoning;
- structured response: `{"status":"ok"}`;
- return code: 0;
- thread ID captured: yes;
- input/output tokens: 17,598 / 15;
- errors: none;
- local evidence: `.local/provider-smoke/f5b9095c395e479689218186f0f39691/`.

## 2026-09-02: Campaign V1 Infrastructure Preflight Failure

The first real job (`omnimech:4`) produced a native candidate and verifier-ready
STL, but the verifier process lacked the optional geometry dependencies. The
recorded result is therefore an infrastructure failure, not a model score:

- campaign: `agent-geometry-30-sol-v1`;
- attempt: `omnimech:4/a001`;
- CAD action return code: 0;
- candidate and mesh existed: yes;
- verifier error: missing `geometry` extra;
- reflection owner: `verifier` with confidence `0.99`;
- reflection decision: stop CAD iteration and repair the evaluation environment;
- durable project integrity: passed, 10 events and 2 verified artifacts.

After installing the verifier dependencies, the unchanged candidate rescored to
`59.12` with 100% metric coverage. This confirms the recorded zero was a false
negative caused by evaluation infrastructure. The v1 directory remains immutable
evidence and is excluded from capability comparisons.

Corrective changes before the formal run:

- add dependency and Codex CLI preflight before any model call;
- bind Python, platform, Codex, OCP, NumPy, SciPy, and Trimesh versions into the
  campaign manifest;
- remove unused CadQuery from the verifier extra and constrain the compatible
  stack to NumPy `<2` and OCP `<7.9`;
- start the formal evaluation under a new campaign identifier.

Formal replacement campaign: `agent-geometry-30-sol-v2`.

## 2026-09-02: Formal 30-Sample Sol Campaign Complete

Frozen condition:

- campaign: `agent-geometry-30-sol-v2`;
- Agent condition: `durable-kernel-compat-v1`;
- loop protocol: `evocad-agent-loop-v2`;
- model: `gpt-5.6-sol`, medium reasoning, through the authenticated Codex CLI;
- paid model APIs used: none;
- selection: all 20 development plus all 10 validation samples;
- hidden test samples used: zero;
- campaign manifest: `506ebd53038d90941757ef7bb6e2dec1c37bc159ac80093fb84053923765e75a`;
- selection digest: `ac9bfc4f89426c4c764ea735c42a64aa1fc75a6f584e6cf4e46712221675f03a`.

Primary results:

- completed projects: 30/30; project integrity: 30/30;
- Pass@1: 16/30 (`53.33%`);
- strict final pass: 22/30 (`73.33%`);
- total geometry attempts: 89; mean attempts: `2.97`;
- first-attempt mean score: `83.26`; selected-checkpoint mean: `97.78`;
- mean recovery gain: `+14.52`; runs improved: 14;
- stop outcomes: 22 strict pass, 5 Agent stop, 2 max-iteration safety
  censoring, and 1 decision-runtime censoring;
- checkpoint rollback selected an earlier best attempt in 6 runs.

Dataset stratification:

- OmniMech: 1/6 strict (`16.67%`), selected mean `90.29`, mean 7.0 attempts;
- Ortho2CAD: 21/24 strict (`87.50%`), selected mean `99.66`, mean 1.96 attempts.

The large dataset gap is a result, not a model-comparison claim. It indicates
that the current benchmark mixes substantially different reconstruction regimes
and must be reported in strata.

Runtime finding and corrective action:

`ortho2cad:00694405` improved from `91.96` to `99.28`, then its feedback turn
timed out and the v2 loop stopped with `decision_unavailable`. This is runtime
censoring, not an Agent decision. Protocol `evocad-agent-loop-v3` therefore
retries decision transport/schema failures twice inside the same geometry
attempt, preserves every decision-turn artifact, and only emits
`decision_unavailable` after those retries or the job-time budget is exhausted.

Paired historical comparison:

Ten `gpt-5.6-sol` samples overlap with `geometry-cost-pilot-v5`: baseline strict
8/10 versus 7/10 here, mean score delta `-0.643`, sign-test `p=1.0`. This is a
descriptive rerun only. The durable compatibility condition did not change the
inner modeling policy, so this comparison is not evidence for or against an
Agent architecture.

Review evidence:

- report: `reports/generated/agent-geometry-30-sol-v2/`;
- review bundle: `reports/generated/agent-geometry-30-sol-v2-review/`;
- embedded review bundle identity:
  `b119237fff25bf2fc712aa7a6e3638eaeb4dad1cd27be484312f630641b2765c`;
- review UI verified with 30/30 runs, 3 interactive synchronized geometry
  viewports, loaded input evidence, immutable review records, and no project
  integrity failures.

## 2026-09-02: Human Review Ingestion Preflight

Three active expert adjudications were verified against the formal v2 review
bundle and its append-only ledger, then compiled into a deidentified
`evocad-human-feedback-v1` manifest. Reviewer identity remains only in the local
review ledger and is not exposed to the Agent or committed to source control.

Routing result:

- `omnimech:4`: `agent_repair` for an `agent_geometry` finding;
- `omnimech:9`: `agent_repair` for an `agent_geometry` finding;
- `ortho2cad:00241318`: `human_clarification` for `input_ambiguity` and a
  missing step-height requirement.

Feedback identity:

- source review bundle:
  `b119237fff25bf2fc712aa7a6e3638eaeb4dad1cd27be484312f630641b2765c`;
- source review ledger head:
  `070670ec0302aab872c613fe468c3529dea90bc9b27654544d09a809ea735b57`;
- feedback manifest:
  `0d74a974f8380cc499fdbf36574de66db08d4f2d9b206c830a766157b9b669bf`.

A dry run against the unchanged 30-sample selection scheduled exactly those
three samples under `durable-kernel-human-feedback-v1`: two repairs and one
durable human gate. No model inference was performed. The follow-up campaign is
an intervention study and must not replace or be pooled with the original
30-sample Pass@1 or strict-pass measurements.

The first live feedback execution was externally interrupted after its work
unit entered `running`. The event chain correctly recorded
`work_unit.interrupted`, but the compatibility plan had only one outer attempt,
so recovery exhausted the work unit before it could re-enter the executor. The
failed campaign remains local evidence and is not reused. Geometry work units
now reserve two outer attempts: one normal execution plus one host-interruption
recovery. The independent inner Agent loop retains its original 12-iteration
safety ceiling. A new campaign identifier is required for the corrected run.

The next live preflight (`agent-geometry-30-sol-human-feedback-v2`) was stopped
during its first model turn. Its trajectory showed that the Agent opened the
feedback through PowerShell, which partially corrupted non-ASCII review text in
the captured console stream. It also interpreted the review record's
`recommended_action: keep` as an instruction to preserve the geometry, despite
the `agent_geometry` issue and repair route. This execution is not scored.

The feedback compiler now emits a route-specific `agent_instruction`, explicitly
separates evaluator workflow actions from modeling actions, and embeds the full
UTF-8 feedback JSON directly in every model and repair prompt. The staged file
remains an auditable copy. Corrected feedback manifest:
`b48ccd1a1976c9852ac7ee35b2b6ead6f5e838a410eca6e862bb89cfa68fea3b`.

## 2026-09-02: Human Feedback Campaign V3

Campaign `agent-geometry-30-sol-human-feedback-v3` completed the two repair
routes and stopped at the intended human gate for the ambiguous sample. It is an
intervention study over reviewed samples, not a replacement 30-sample score.

Repair outcomes:

- `omnimech:4`: first attempt `11.29`, selected `99.75` at a006 after 8
  attempts, autonomous stop, no strict pass;
- `omnimech:9`: first attempt `20.89`, selected `97.92` at a007 after 9
  attempts, autonomous stop, no strict pass;
- `ortho2cad:00241318`: blocked before model or CAD execution with
  `human_clarification_required`; the missing first-step height must be supplied.

Both repair runs improved substantially over their own first attempt, selected
an earlier best checkpoint after later regressions, and ended without safety or
runtime censoring. Mean first-attempt score was `16.09`; mean selected score was
`98.84`. Across 17 attempts the loop recorded 8 recoverable Core Console job
failures, zero failed MCP calls, and zero project-integrity failures.

Relative to the original v2 selected checkpoints, the specific written review
for `omnimech:4` improved `99.40` to `99.75`; the label-only review for
`omnimech:9` regressed `99.86` to `97.92`. This result does not establish a
general feedback benefit. Future feedback evaluation must stratify by review
specificity and compare against a no-feedback rerun under the same loop version.

Review artifacts:

- report: `reports/generated/agent-geometry-30-sol-human-feedback-v3/`;
- two-run 3D review bundle:
  `reports/generated/agent-geometry-30-sol-human-feedback-v3-review/`;
- review bundle identity:
  `cf3e06c6196e584f53c9982cef5f9e0ed45b8c9d2d62479b9360e61b0588ca5d`;
- local review URL: `http://127.0.0.1:8769/`.

The report materializer records blocked work units separately and excludes them
from geometry-score aggregates instead of fabricating a zero-score CAD result.
