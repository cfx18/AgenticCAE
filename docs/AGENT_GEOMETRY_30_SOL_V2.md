# Agent Geometry 30 / Sol V2 Review Memo

## Decision status

The implementation and fixed 30-sample evaluation are complete. The next
required step is human semantic review of the evidence and verifier decisions,
not another blind batch run.

## Frozen bindings

- Campaign: `agent-geometry-30-sol-v2`
- Model: `gpt-5.6-sol`, medium reasoning
- Provider: authenticated Codex CLI; no paid API integration
- Samples: 30 frozen development/validation cases; no hidden test use
- Campaign manifest SHA256:
  `506ebd53038d90941757ef7bb6e2dec1c37bc159ac80093fb84053923765e75a`
- Selection SHA256:
  `ac9bfc4f89426c4c764ea735c42a64aa1fc75a6f584e6cf4e46712221675f03a`
- Agent results SHA256:
  `893f84f67b534a2be9590c167d5d61ef424155aa35c94dd08c51e8fae4a806fa`

## Results

- Pass@1: 16/30 (`53.33%`)
- Strict final: 22/30 (`73.33%`)
- First mean: `83.26`; selected mean: `97.78`
- Mean recovery: `+14.52`
- Attempts: 89 (`2.97` per run)
- Integrity: 30/30
- Stop reasons: 22 strict pass, 5 Agent stop, 2 safety ceiling, 1 runtime censor

The paper-ready overview is
`reports/generated/agent-geometry-30-sol-v2/agent-evaluation.png`. The full
tables and trajectories are in the same directory.

- Figure SHA256:
  `19f0bab77c3afe3d1a92c1eb43943af7b5aef296ff2c2d89ce4295ae88f927e2`
- Review bundle identity:
  `b119237fff25bf2fc712aa7a6e3638eaeb4dad1cd27be484312f630641b2765c`

## Failures to review

- `omnimech:4`: 99.40, Agent stop, 5 attempts, selected `a003`
- `omnimech:9`: 99.86, Agent stop, 8 attempts, selected `a006`
- `omnimech:2`: 66.43, max-iteration safety ceiling, 12 attempts, selected `a012`
- `ortho2cad:00241318`: 98.11, Agent stop, 5 attempts, selected `a004`
- `ortho2cad:00694405`: 99.28, decision runtime censor, 3 attempts, selected `a002`
- `ortho2cad:00186338`: 94.36, max-iteration safety ceiling, 12 attempts, selected `a012`
- `omnimech:10`: 76.14, Agent stop, 6 attempts, selected `a004`
- `omnimech:6`: 99.93, Agent stop, 9 attempts, selected `a007`

## Human review protocol

1. Review all eight non-passing runs, especially the five scores above 98, and
   decide whether the strict threshold reflects meaningful geometry error.
2. Review a balanced sample of strict passes from both datasets to estimate
   verifier false-positive risk and ground-truth/input ambiguity.
3. For disputed cases, assign issue ownership and record a recommended action in
   the immutable review UI. Do not overwrite verifier artifacts.
4. Treat `ortho2cad:00694405` as censored in v2. Protocol v3 already adds two
   non-geometric decision retries; a later v3 campaign can measure the effect.

## Interpretation limits

The 10-sample overlap with `geometry-cost-pilot-v5` is descriptive only. It does
not isolate an Agent architecture change. The next causal comparison should keep
the model, frozen samples, verifier, AutoCAD backend, and budgets fixed while
changing only a declared planner/memory/diagnosis policy.
