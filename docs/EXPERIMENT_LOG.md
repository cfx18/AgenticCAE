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

## 2026-09-02: Native B-Rep Feature Localization Prototype

The second localization stage added a workspace-built AutoCAD managed plugin
and three non-restrictive MCP tools for asynchronous native topology export.
`autocad_core_start` still accepts arbitrary AutoLISP; an optional operation
manifest now records intent and the final solid handles observed by the backend.

Real-DWG validation used `omnimech:4` attempts from the human-feedback v3
campaign:

- a008 exported one solid with 5,247 faces, 15,631 edges, and 10,391 vertices
  in 11.9 seconds with zero entity export errors;
- unwrapping trimmed external geometry resolved 5,216 planar, 28 cylindrical,
  and 3 conical faces, plus 15,180 line, 440 circular, and 11 NURBS edges;
- a001 exported a compact 9-face graph with 20 face adjacencies and 2 analytic
  feature candidates;
- an end-to-end low-score diagnostic produced four mismatch regions and ranked
  native candidate faces for every region;
- exact native queries used 36 retained surface points across those four regions;
  both candidate-to-truth regions mapped to their AutoCAD faces at zero native
  surface distance after automatically recovering the `STLOUT` translation
  `[-30.002117, -30.000001, -8.000001]`;
- an isolated Core Console provenance test recorded final solid handle `2C1`
  against the declared operation without changing the unrestricted payload.

These checks establish transport, extraction, alignment, graph construction,
exact point-to-face query, and persistence. They do not establish exact design-history
recovery or calibrated feature-class precision.

## 2026-09-03: Frozen 30-Run Native Feature Backfill

The selected checkpoints from `agent-geometry-30-sol-v2` were re-scored and
enriched in a separate, hash-bound derived campaign. No source result, verdict,
candidate, or trajectory was modified.

- 30/30 selected DWGs exported native B-Rep topology; zero export failures;
- 10 checkpoints produced 69 localized mismatch regions;
- all 69 regions received an exact candidate-face or nearest-boundary assignment;
- 40/69 assignments met the current vote-based high-confidence rule;
- all 36 candidate-to-ground-truth regions were within normalized face distance
  `0.006` (33 at numerical zero);
- all 33 ground-truth-to-candidate regions exceeded `0.006`; their median nearest
  candidate-boundary distance was `0.006629`;
- 23/69 regions intersected an inferred analytic feature candidate;
- 0/69 linked to an Agent-declared operation because the historical v2 audit
  predates operation manifests. This is a baseline limitation, not an exporter
  failure.

Assignment coverage is not reported as localization accuracy because this split
does not contain expert face-attribution labels. Missing-region queries identify
the nearest surviving candidate boundary, not the absent feature itself.

Artifacts:

- backfill: `reports/generated/agent-geometry-30-sol-v2-feature-backfill-v1/`;
- analysis: `reports/generated/agent-geometry-30-sol-v2-feature-backfill-analysis/`;
- backfill manifest: `01e6963a11057492d9534874ec16cce3ea75fa4a1e740e2b1409061dc7863351`;
- analysis inputs bind the backfill summary SHA-256
  `0a37a209a83c32cbdb19b7323f0319a3af7335649088eb91b5e9b9745a9dc9d3`.

## 2026-09-03: Process-Independent Campaign Recovery

The Agent condition advanced from `durable-kernel-compat-v1` to
`durable-kernel-checkpoint-v2`. The new condition adds a detached workspace-local
runner and `geometry-attempt-checkpoint-v1` without changing AutoCAD geometric
operation freedom or verifier thresholds.

An injected interruption test killed the feedback decision after action and
verification. Recovery retained one ledger attempt, did not rerun geometry or
scoring, reused the Codex thread, preserved `decision-turns/t01`, and completed
through `decision-turns/t02`. Separate state boundaries retain completed action
work when verification is interrupted and archive partial action traces before
an in-attempt action retry.

Campaign `agent-geometry-30-sol-native-feedback-v2` remains interrupted evidence
under its original source binding. It must not be resumed with the new code. The
replacement 30-sample campaign uses a new identifier and freezes the checkpoint
condition before execution.

## 2026-09-03: Native Feedback V3 Complete and Boolean Lineage Condition

Campaign `agent-geometry-30-sol-native-feedback-v3` completed 30/30 projects
under its frozen `durable-kernel-checkpoint-v2` condition:

- Pass@1: 14/30 (`46.67%`);
- strict final pass: 26/30 (`86.67%`);
- first-attempt mean: `82.02`;
- selected-checkpoint mean: `98.76`;
- attempts: 93, mean `3.10`;
- stops: 26 strict pass, 3 Agent stop, 1 max-iteration safety censor;
- project integrity: 30/30.

Against `agent-geometry-30-sol-v2` on the same 30 samples and
`gpt-5.6-sol/medium`, strict passage changed from 22/30 to 26/30 with four gains
and zero losses. Mean selected score changed by `+0.9793`; the paired strict-pass
sign test is `p=0.125`. This is a historical paired comparison, not a randomized
A/B, and does not isolate one implementation component.

Failure-path inspection showed that spatial localization still mapped each
region to roughly 2-6 operations through a shared final entity handle. The next
condition, `durable-kernel-boolean-lineage-v3`, therefore captures native BRep
topology immediately before and after every unrestricted Core Console job. It
uses stable face fingerprints to distinguish inherited faces from
created-or-modified faces and carries parameter-bearing operation DAG nodes into
verifier feedback. Multi-operation jobs remain explicitly ambiguous.

Real AutoCAD validation passed for primitive creation and subtractive Boolean
editing. The subtractive check retained four unchanged box faces and attributed
the two modified end faces plus the new cylindrical wall to a single centered
through-hole operation. Detailed protocol and limits are recorded in
`docs/BOOLEAN_FACE_LINEAGE.md`.

### Lineage pilot V1 and corrective versioning

The targeted two-sample campaign `agent-geometry-lineage-pilot-sol-v1` completed
without runtime or safety censoring:

- `omnimech:4`: selected `99.82` at a004 versus native-feedback V3 `99.77`;
- `ortho2cad:00186338`: selected `99.85` at a005 versus V3 `99.15`;
- both runs stopped autonomously without strict passage.

The Agent emitted parameter-bearing staged operations and began isolating
repair hypotheses. Inspection also found that the first lineage implementation
compared only the final Core job. It correctly labeled 102 inherited and 3
changed faces in `omnimech:4/a001`, but did not propagate the origin of inherited
tooth faces from earlier jobs. A separate reasoning defect appeared after an
`ortho2cad` regression: the reflection requested the best checkpoint but called
the regressed parameter set successful and proposed replaying it.

The corrected condition is `durable-kernel-boolean-lineage-v4` with protocol
`evocad-boolean-face-lineage-v2`. It propagates face origins through the captured
input/output job graph, excludes validation-only operations from geometric
causality, and adds an adjudication rule against replaying a regressed parameter
set without new contradictory evidence. Offline replay of the unchanged V1
artifacts linked all major tooth mismatch regions only to
`op03_tooth_spaces/tooth_pattern`; keyway and radial-hole regions linked to their
own operations, and `op07_final_validation` disappeared from candidates.
