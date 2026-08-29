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
```
