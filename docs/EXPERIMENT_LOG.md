# EvoCAD Experiment Log

## Native Astra Ultra on OmniMech 4, 2026-09-14

Ran the requested additional sample with native Codex + Astra Ultra and the same
source-only prompt, HTTPS transport, AutoCAD MCP and geometry-v2 scoring (20k/64).
Completed normally in 914.472 seconds: **100.0**, strict pass, IoU **0.993030**,
normalized Chamfer **0.003613**, volume error **0.4666%**. No GT feedback, forced IR,
external repair or human mirror correction. Agent-disclosed approximations include
an inferred 28 mm length, smooth nominal M6 openings and minor edge treatments.

Published `direct-astra-4` under Codex in the unified review catalog. Preserved
four DWG intermediates, source overlays, construction record and public trajectory.
The post-archive ledger verifies 68 files / 53 events. Historical EvoCAD/Sol medium
was 99.4 / strict fail / IoU 0.972953; this is not a single-variable comparison.

A post-run topology export unexpectedly rewrote the input DWG. Hash checking
caught it; the byte-identical scored original was restored from the preserved
copy, with incident evidence retained. Topology jobs now open an isolated copy;
the repaired export leaves the original unchanged. No original score was changed.
32 regression tests passed. Details: `docs/experiments/native-astra-ultra-omnimech4.md`.

## Astra OmniMech 2 Mirror Diagnostic, 2026-09-14

Following the user's mirror hypothesis, rescored the unchanged original and
three axis-reflected meshes using the unchanged geometry-v2 protocol (20k/64).
Original score 91.69 / IoU 0.890819 reproduced exactly. Each reflected mesh passed
strictly at score 100 / IoU 1. A native AutoCAD mirror about WCS `y=32`, followed
by independent export, also scored 100 / IoU 1 / normalized Chamfer 0.004546.
Native volume, area and bounds were unchanged; only handedness changed.

This is a human-requested, GT-assisted diagnostic, not an autonomous Astra repair.
No new model call, verifier modification or original score/review overwrite.
Separate parent-linked ledger verified 22 files / 20 events. Review catalog entry
`mirror-astra-2` under Diagnostics contains original and mirror for comparison.
Details and caveats: `docs/experiments/astra-omnimech2-mirror.md`.

## Native Astra/Sol Ultra on OmniMech 2 and 10, 2026-09-14

Completed the three requested independent native Codex runs with the same CLI,
HTTPS transport, unchanged source-only prompt, AutoCAD MCP, ultra effort label,
3,600-second safety cap and held-out geometry-v2 scoring:

- OmniMech 2 / Astra: 91.69, strict fail, IoU 0.890819, 929.209 seconds.
  Previous native Sol Ultra: 63.34, strict fail, IoU 0.878517.
- OmniMech 10 / Sol: 100.0, strict pass, IoU 0.999824, 981.899 seconds.
- OmniMech 10 / Astra: 100.0, strict pass, IoU 0.999824, 705.037 seconds.

All three stopped normally without external repair turns or in-run GT feedback.
Astra recovered its OmniMech 2 final-save Core Console crash autonomously. Sol
corrected its OmniMech 10 T-slot and underside-feet interpretation within the run.
The account remained available; no reset credit or separate paid API was used.

New frozen bundles are registered under Codex as `direct-astra-2`, `direct-sol-10`
and `direct-astra-10`. Existing `direct` remains the original Sol / OmniMech 2.
Native CAD intermediates, inspection images, public root/helper trajectories and
MCP audits are preserved. Post-archive ledgers verify at 61/59/53 files respectively.
See `docs/experiments/native-ultra-omnimech2-10.md` for configurations, hashes,
metrics, root usage, review URLs and comparison caveats. These are single-trial
observations on two parts, not evidence for a general model ranking.

## Unified Harness Review Navigation, 2026-09-14

Added Harness (EvoCAD / Codex) and Experiment selectors to the upper-left review
browser. The servers on 8770 and 8765 now expose six registered historical views
through one page. Switching retains the same sample where available, remembers
the last experiment per harness, and scopes unsaved drafts by exact evidence.
The two-sample human-feedback V3 view remains clearly distinct from a full campaign.

No modeling, scoring, candidate changes, or migration of review records occurred.
All six frozen bundles and their ledgers verified successfully; the three original
human reviews remain attached to the original V2 bundle. Existing bundle/UI files
were not overwritten. The shared navigation UI has its own immutable presentation
snapshot (`d19ea0768bbed68d62400950b62f20ea6ebc24024602fbd117aee4b1c57ca8fe`),
and new reviews additionally bind to that presentation and catalog. Requests are
bundle-scoped; stale save identities are rejected.

Validation: 23 Python review/export/API tests and 6 Node navigation tests passed.
Tests cover independent ledgers, old-review preservation, unchanged assets,
presentation tampering, unknown/path-escaping routes, draft isolation, failed-load
rollback, stale-response races, and navigation during saves. Live browser checks
verified Codex `omnimech:2` (63.34) -> EvoCAD V2 same sample (66.43), V3 view selection,
the three original reviews, synchronized geometry dragging, and a 390px mobile
viewport. Browser warning/error log was empty. No test reviews were submitted to
real ledgers.

## Native Codex / Sol Ultra / OmniMech 2, 2026-09-14

Completed the user's direct native-Codex comparison on the selected `omnimech:2`
case. The successful execution campaign is
`direct-codex-sol-ultra-omnimech2-https-20260914`: Sol ultra, source-only input,
same AutoCAD MCP, no EvoCAD outer loop, no forced IR, no in-run GT feedback.
The default-transport first run was preserved as infrastructure-interrupted;
its missing-output zero is not a geometry score and is excluded from comparison.

Native Codex voluntarily stopped after 1,679.828 seconds (28.0 minutes), producing
one editable solid. Composite **63.34**, IoU **0.878517**, normalized Chamfer
**0.009053**, bounds error **0**, volume error **5.1968%**, strict **fail**.
Historical V2: score 66.43 / IoU 0.747455 / volume error 0.0108%.
Historical V3: score 72.92 / IoU 0.802343 / volume error 0.4266%.
The native result improves overlap and surface distance, but loses the entire
20-point volume component. Do not reduce this tradeoff to a blanket harness win
or loss. Effort, feedback access, CLI version and budgets differ from history.

Ultra itself spawned three native helpers (dimensions, strategy, drawing audit).
The main task cropped the input, built a first solid, checked native topology,
corrected 0.5 mm offsets, rendered four views, then audited and saved the final
DWG. It was not cut off by a repair-count or time limit. Its self-evaluation did
not detect all remaining geometry errors. No follow-up repair run has been made.

Details and reproducibility: `docs/experiments/direct-codex-sol-ultra-omnimech2.md`.
New review: `http://127.0.0.1:8770/` (`start-review.ps1 -View direct`), with a
separate immutable human-review ledger. Original review services are unchanged.
Rendered evidence, native DWG/STL/topology, prompts, Codex events, MCP audit and
supplementary public native-helper snapshots are retained under the workspace.
The new page was browser-verified, including synchronized 3D rotation.

## Results recap checked on 2026-09-14

This recap distinguishes completed capability runs from diagnostics and proposed
work. No CAD modeling or model evaluation was rerun for the recap.

- Early CAD-1000-hours pilot (`pilot-v4-20260829`): 24 runs, 3 passes,
  mean EQC 72.98; Sol/Terra/Luna means 76.90/73.30/68.75. This used the
  earlier custom rubric and must not be compared numerically to later geometry
  or BenchCAD scores. Input ambiguity motivated the switch to geometry GT.
- Three-model geometry pilot: 10 samples per model, 30 runs, not 30 samples per
  model. V2 strict passes were 6/10 for each model. The revised feedback loop V5
  yielded Sol 8/10, Terra 6/10, Luna 4/10; mean selected scores were
  99.88/91.22/72.65. These are historical reruns, not isolated causal effects.
- Frozen Sol 30-case study: `agent-geometry-30-sol-v2` strict final 22/30
  (73.33%), selected score mean 97.78; native-feedback V3 strict final 26/30
  (86.67%), mean 98.76. Pass@1 changed 16/30 to 14/30. The paired final-pass
  comparison has four gains, no losses, and sign-test p=0.125. These are the same
  24 Ortho2CAD and 6 OmniMech cases, but multiple implementation changes are
  confounded. V3 strict results by dataset: Ortho2CAD 23/24, OmniMech 3/6.
- Human feedback: two repairs, one unresolved input-requirement gate. Relative
  to prior selected scores, OmniMech 4 changed 99.40 -> 99.75 and OmniMech 9
  changed 99.86 -> 97.92; neither repair strict-passed. No general benefit is
  established by these interventions.
- Boolean-lineage V2 diagnostic: OmniMech 4 selected 99.87; Ortho2CAD 00186338
  selected 99.68 with a decision-transport censor. The separately frozen recovery
  selected 99.25 across 14 attempts and reached its safety ceiling. No strict
  passes or population-level conclusion from these targeted runs.
- Exact-feature oracle on Ortho2CAD 00186338: both unordered exact features and
  ordered plans strict-passed in one attempt (100.0, IoU 0.999108). Subsequent
  input-identifiability probes found only three printed overall dimensions;
  oracle success therefore supplies hidden information and does NOT establish
  that all error in the ordinary image task belongs to the Agent or model.
- IR single-case diagnostic on that sample: forced IR score 98.95 / IoU
  0.960214; specialist IR score 99.95 / IoU 0.988461; exact oracle IR score
  100.0 / IoU 0.999108. The first two did not strictly pass. A single case
  cannot establish specialist-IR superiority.
- BenchCAD 30-family study, Sol medium: baseline 30/30 scored, mean official
  voxel IoU 0.7383129; forced IR 30/30 scored, 0.7412019. Specialist IR
  stopped at 3/30, mean 0.4187917, by user decision after early degradation.
  Its mean is not comparable to the complete 30-case means. In the forced arm,
  first-checkpoint mean was 0.602363; post-hoc best-checkpoint mean was 0.777236
  versus actual submitted mean 0.741202. Oracle selection is diagnostic only.
- OpenHands adoption and a matched upstream BenchCAD harness comparison were
  discussed, not implemented or evaluated in these saved results.

Geometry selected score (0-100), strict-pass rate, and BenchCAD mean voxel IoU
(0-1) are distinct metrics. Strict geometry passage requires all frozen
thresholds, not merely a rounded score near 100. The detailed primary sources
are the named campaigns' `summary.json`, `paired-sol-comparison.json`, and
`evals/geometry-benchmarks/reference-runs/`.

### Review service recovery

The old review ports were not listening. The workspace-local launcher
`apps/geometry-review/start-review.ps1` now starts hidden loopback servers,
checks the bundle identities, and reuses matching live servers. Restart after
an OS reboot with the command in the review README; no system service was added.

Browser verification exposed a separate first-load frustum initialization bug:
camera projection bounds were not recomputed when geometry changed scale.
The source viewer now updates projection bounds during camera synchronization.
`refresh_geometry_review_app` creates a separately hashed UI-only derivative,
preserving source files, cached assets, campaign, scores, and all trajectories.
No previous human adjudication is silently rebound to the new UI.

- Recommended geometry page: `http://127.0.0.1:8765/`, 30 Sol V2 records with
  post-hoc native feature localization and a repaired display, NOT the V3 rerun.
- Original V2 adjudications: `http://127.0.0.1:8766/`, all three reviews retained.
  This frozen historical UI retains the initial camera-frustum defect.
- Lineage / recovery / feedback snapshots: ports 8767 / 8768 / 8769.
- New display bundle: `agent-geometry-30-sol-v2-feature-review-display-v2`;
  SHA-256 `7f65b1c4b53df7982c083e30bf453461855d2ab7b11863d4734ac8652dc21ff8`;
  parent `f8e9145c5c4d0c46a7e7dcbb33acf587d520e53c88fe0b7c4ee5ff55d2409fac`.
- Verification: 14 geometry-review tests passed, including immutable refresh,
  unchanged cached evidence, corrupt-source rejection, and HTTP serving tests.

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

### Lineage pilot V2 and recovery replicate

Campaign `agent-geometry-lineage-pilot-sol-v2` evaluated the corrected
multi-job lineage condition on the same targeted pair. This remains a diagnostic
pilot, not a population estimate:

| Sample | Pre-lineage V3 | Boolean-lineage V2 | Attempts | Stop |
| --- | ---: | ---: | ---: | --- |
| `omnimech:4` | 99.77 | 99.87 | 8 | Agent stop |
| `ortho2cad:00186338` | 99.15 | 99.68 | 6 | decision transport unavailable |

Neither condition strictly passed either sample. The V2 mean selected-score
delta over these two historical pairs is `+0.315`, but the ortho2cad run is
runtime-censored and the comparison is neither randomized nor large enough for
an accuracy claim.

The interrupted ortho2cad sample was repeated unchanged in the separately
frozen campaign `agent-geometry-lineage-pilot-sol-v2-recovery1`. It improved
from `41.85` to selected checkpoint `a013=99.25` across 14 attempts. The final
attempt scored `99.03`; the Agent requested another distinct repair, so the run
is correctly recorded as `max_iterations` safety-censored rather than an
autonomous stop. Project integrity passed over 275 checked files and 349 ledger
events.

The recovery trajectory supplies qualitative evidence unavailable in the old
condition. It cited inherited native faces when preserving geometry, restarted
from the best checkpoint after score regressions, separated IoU gains from
volume regressions, derived volume-balanced parameter hypotheses, and recovered
five Core Console job failures without desktop intervention. A single-parameter
lever-notch experiment improved the best score from `98.82` to `98.91`.

Important limitations remain. The Agent often placed several declared
operations in one Core Console job, leaving changed faces attributable only to
an operation group. The near-perfect `omnimech:4/a004` result produced no
surface regions at the fixed localization threshold, so lineage had no residual
region to explain. Finally, the safety cap cannot yet resume the same project
and thread as a follow-on campaign even when the last reflection requests a
defensible next experiment.

Artifacts:

- original V2 report and paired comparison:
  `reports/generated/agent-geometry-lineage-pilot-sol-v2-vs-native-feedback-v3/`;
- original V2 review: `http://127.0.0.1:8767/`;
- recovery report:
  `reports/generated/agent-geometry-lineage-pilot-sol-v2-recovery1-vs-native-feedback-v3/`;
- recovery review: `http://127.0.0.1:8768/`;
- recovery review bundle SHA-256:
  `c341c7c157475a22c98d47da3a5b5255c320b8753641556cc778a73bbab4db5e`.

The report pipeline was also corrected to persist normalized `results.json`,
accept either a raw campaign or report snapshot as a baseline, and label paired
campaigns generically instead of hard-coding a 30-sample native-feedback name.

### GT trajectory attribution harness

Normal failure trajectories were judged insufficient to distinguish Agent design
from base-model capability: they show the realized policy failing, but both factors
are changed together. Protocol `evocad-trajectory-attribution-v1` now preregisters a
paired oracle ladder on a fixed sample/model/tool/verifier/budget configuration:
normal, exact unordered feature inventory, exact ordered feature DAG, and direct GT
execution. Oracle campaigns are hash-bound, marked as evaluation-only interventions,
and excluded from normal accuracy.

The static AST extractor was validated on all 40 local Ortho2CAD programs without
executing dataset code. It recovered 132 feature nodes: 86 extrusions, 27 unions,
and 19 cuts. For `ortho2cad:00186338`, it recovered four extrusion features, three
unions, and four final-solid checkpoints. The GT STEP scores `100.0` against itself
under the frozen strict verifier, ruling out final-artifact self-inconsistency for
this case. Executable CadQuery replay is currently recorded as unavailable because
the workspace runtime provides OCP but not the `cadquery` wrapper; this is treated as
a missing counterfactual, not as an execution failure.

At the initial reporting checkpoint, attribution was `not_identified`: the `99.25`
recovery trace was available while oracle counterfactuals had not completed.
Generated local artifacts are under
`reports/generated/gt-attribution-00186338/` and the method is documented in
`docs/GT_TRAJECTORY_ATTRIBUTION.md`.

The first paired oracle replicate subsequently completed under the same sol model,
reasoning effort, iteration/time budget, AutoCAD MCP, and strict verifier. Both the
unordered perception oracle and ordered plan oracle strict-passed at `100.0` on the
first attempt. Their IoUs were both `0.999108`; normalized Chamfer was `0.002941`
and `0.002947`, respectively. In contrast, the normal recovery run required 14
attempts and selected `99.25` with IoU `0.968739`.

This establishes a sample-level diagnostic attribution to the
observation-to-feature-inference stage: exact features are sufficient for the same
model to use the same tools successfully, even without feature order. It does not
yet separate Agent observation design from sol's visual inference capacity inside
that stage, and it does not establish a population causal rate because only one
oracle replicate was run. The immutable
summary and artifact hashes are recorded in
`evals/geometry-benchmarks/reference-runs/gt-attribution-00186338-r1.json`.

An input-identifiability audit then tested whether the perception oracle had added
information absent from the normal task. Three independent, ephemeral sol probes
were run with a read-only sandbox, empty MCP configuration, and prohibited-tool
event checks. All three extracted exactly the same printed dimensions: overall
height `0.7421`, overall length `0.7500`, and overall width `0.2656`. All three
judged the drawing dimensionally incomplete, and no probe used a tool.

Only 3 of 29 descriptive GT feature values matched explicit dimensions at displayed
precision; 26 internal profile, location, arc, and thickness values were not
explicitly constrained. Because those values may include dependent coordinates,
the `10.34%` figure is descriptive rather than a formal degrees-of-freedom measure.
The unanimous observation of only three overall dimensions is sufficient to revise
the sample-level conclusion: Agent-versus-model ownership is confounded by input
specification. The exact-feature oracle proved execution capability but also supplied
hidden information, so its success cannot be charged to normal perception failure.

## 2026-09-15: EvoCAD + Astra Ultra On OmniMech 2

Campaign `evocad-astra-ultra-omnimech2-https-20260915` completed with baseline
EvoCAD, `gpt-6-astra` / `ultra`, the original drawing and no human mirror hint,
prior candidate, forced IR or oracle input. The first scored candidate `a001`
strict-passed at 100.0, IoU 1.000000, normalized Chamfer 0.004563, zero bbox error
and 0.0483% volume error. After receiving verifier feedback, the Agent chose to
stop because no supported score improvement remained. There was no repair round.

Native Codex + Astra Ultra previously scored 91.69 on the same sample. The +8.31
point difference is descriptive and does not identify a causal harness advantage:
there is only one sample/run, prompts and orchestration differ, and this success
preceded score feedback. A host interruption required supervisor recovery of the
same conversation and staged geometry. The review's 705.036 seconds describe the
resumed attempt; initial launch to completion was 1594.503 seconds, including
interruption/recovery. Raw resumed CLI token counters appear cumulative, so the
harness sum must not be used as verified billable usage.

Full conditions, caveats and evidence hashes:
`docs/experiments/evocad-astra-ultra-omnimech2.md`. The new review entry is
`http://127.0.0.1:8770/?view=evocad-astra-2`, under Harness `EvoCAD`; original Codex
and human mirror diagnostic bundles remain unchanged. Postrun ledger verification
passed for 218 files and 214 events, with 171 additional artifacts preserving
staged DWGs, native jobs, interrupted traces and supervisor recovery. The review
shows all three interactive geometry panels and synchronized camera rotation.

### Astra Historical Evidence Library

The four completed Astra model runs (native OmniMech 2/4/10 and EvoCAD OmniMech 2)
and the separate human mirror diagnostic now have a shared read-only evidence UI
at `http://127.0.0.1:8770/astra.html`. No CAD/model executions were repeated.
The five exports contain 1,000 manifest-indexed files, 292 CLI events, 67 MCP
calls and 28 native jobs including the one human operation. Interrupted phases,
postrun snapshots and evaluator incidents are explicitly distinguished.

All exported-file and ZIP hashes passed. The UI supports per-run I/O search,
native Lisp/log browsing, file preview and complete archive download. Existing
geometry review remains linked and its scores/ledgers are unchanged. Verification
passed 34 Python and 9 JavaScript tests plus browser checks; details and immutable
presentation binding are in `docs/ASTRA_RECORDS.md`.

### CADGenBench 111: Native Astra Ultra With Local AutoCAD

On 2026-09-16, ran generation fixture 111 with native Codex, `gpt-6-astra`,
`ultra`, and the locally installed AutoCAD 2024 through the audited MCP. Only
the official frozen drawing and description were supplied. The conversation
completed in 2113.689 seconds, without GT feedback or human geometry hints.
One connected native solid and a matching SAT roundtrip passed local validity
checks. Two failed side-port jobs were autonomously repaired; a visual ear-blend
correction was also self-initiated. Several minor dimensions remain inferred.

Official benchmark score is unknown: the GT is private and no public submission
was made. Fourteen agent checks and the supervisor's watertight mesh check must
not be interpreted as official accuracy. Archived 156 CLI events, 31 MCP calls,
15 native jobs and 193 hash-verified files. An inventory-only launcher typo was
fixed and the final summary recovered from persisted completion state without
rerunning the model or editing geometry. Details, hashes, and limitations:
`docs/experiments/cadgenbench-111-native-astra-ultra.md`.
