# EvoCAD Experiment Log

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
