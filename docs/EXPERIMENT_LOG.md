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
