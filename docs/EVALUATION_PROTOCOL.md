# CAD-EvoLoop Evaluation Protocol

Protocol version: 1.0, 2026-08-29

## Evaluation Boundary

The drawing agent receives exactly `task_desc.json` and files below
`input_files/`. The batch runner copies that allowlisted bundle into an isolated
job directory. `rubrics.json`, `metadata.json`, completed dataset outputs, and
the original sample directory remain evaluator-only. Symlinks and undeclared
files in an agent bundle are rejected.

The campaign manifest records SHA-256 hashes for both sides of this boundary.
It is immutable after creation and binds the dataset manifest, split, sample
membership, model configurations, execution budgets, effective source files,
Git state, Python version, and platform. Resuming a campaign with drift fails
instead of silently mixing conditions.

## Protocol Modes

- `development`: only development split samples are accepted. Adaptive prompt,
  skill, MCP, or verifier changes are allowed in isolated candidate workspaces.
- `pilot`: fixed-system measurement on either pilot split. Results are useful
  for engineering and protocol calibration, not final claims.
- `frozen-evaluation`: development samples and dirty or uncommitted source trees
  are rejected. The explicitly supplied split must declare `purpose` as
  `paper-final` and `sealed` as `true`; all system sources and thresholds must
  have been frozen before it is opened.

The current 40/10 split is a development and pilot split. It is not the final
paper test set.

## Closed Agent Loop

New geometry campaigns use `evocad-agent-loop-v3`; completed v2 campaigns keep
their original binding. One logical iteration consists
of a CAD action, deterministic verification of that exact candidate, and a
same-thread agent adjudication. The adjudication records failure ownership,
observed evidence, root causes, whether the current structure can improve, a
concrete next-action plan, and `continue` or `stop`. Only `continue` schedules a
new CAD action. The next action starts from the best scorable checkpoint while
also receiving the latest verdict, so a broken Boolean or empty-solid
regression does not replace a valid earlier result.

`max_iterations` is an external safety ceiling, not an agent reasoning budget.
The agent still receives and adjudicates the verifier result at the ceiling;
the ledger records both its requested decision and the harness safety stop.
Strict pass, job time exhaustion, adjudication unavailable after transport
retries, and the safety ceiling are hard stops. A timeout, missing response, or
schema-invalid adjudication is retried twice inside the same geometry attempt;
each decision turn remains an immutable artifact. Consecutive non-improvement
is advisory only.

The same adjudication may attribute a defect to the prompt, skill, MCP,
verifier, harness, or task and record a system-change proposal. Fixed campaigns
do not mutate shared components mid-run; those proposals enter the versioned
outer improvement workflow and require separate validation before adoption.

## Primary Metric

Evidence-Qualified Completion (EQC) is computed from check-level evidence:

```text
EQC = 100 * passed rubric weight / total rubric weight
coverage = 100 * (passed + failed) rubric weight / total rubric weight
conditional accuracy = 100 * passed rubric weight / verified rubric weight
```

An unverified check contributes to the denominator and zero to EQC. A visual
verdict may resolve an unverified deterministic check only by its existing check
identifier; invented or duplicate identifiers are rejected. An unresolved or
failed hard gate prevents task success. Empty and infrastructure-error verdicts
always produce zero EQC.

For batch runs, candidate scenes are rendered to neutral images and only
deterministically `unverified` rubric checks are sent to the configured Codex
VLM. The evaluator runs read-only with MCP disabled. Accepted visual evidence is
fused before EQC is computed; the resulting EQC success controls repair and
termination. `legacy_status` is retained only for backward-compatible analysis.

The legacy nominal verifier score remains in artifacts for compatibility. It is
not the primary paper metric.

## Reporting

Report per-run results rather than selecting the best attempt. Aggregate EQC,
coverage, task success, recovery, attempts, wall time, token use, CAD failures,
and verifier error rates with paired bootstrap 95 percent confidence intervals
over workflows. Disputed verifier decisions and a random sample of accepted
decisions require expert audit.

Every table and figure must be generated from a validated campaign manifest and
an integrity-checked ledger snapshot. Generated reports must include the
campaign manifest digest.

## Commands

```powershell
cad-evoloop-batch --campaign dev-01 --all-samples --protocol-mode development
cad-evoloop-batch --campaign paper-01 --all-samples --protocol-mode frozen-evaluation `
  --split-manifest configs/campaigns/paper-final-split.json
cad-evoloop-eqc --verdict path/to/verdict.json --output path/to/eqc.json
cad-evoloop campaign-verify path/to/campaign-manifest.json
cad-evoloop report path/to/campaign --output reports/generated/campaign-name
cad-evoloop verifier-replay path/to/campaign --campaign calibration-name `
  --output evals/cad-1000-hours/improvement/campaigns/calibration-name
```

`verifier-replay` reuses the selected native DWG checkpoints from a completed
campaign. It freezes a new verifier manifest and recomputes deterministic,
native-render, visual, and fused evidence without invoking the drawing agent.
