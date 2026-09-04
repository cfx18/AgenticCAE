# GT Trajectory Attribution

EvoCAD uses ground-truth construction programs as evaluator-only interventions. They
are never included in a normal geometry campaign. The purpose is to separate four
failure layers that cannot be identified by reading a normal trajectory alone.

## Intervention ladder

Let `Y(c)` be strict pass/fail for the same sample, model, tools, verifier, and
budget under condition `c`:

- `normal`: images and closed-loop verifier feedback only;
- `perception`: additionally supplies an unordered exact feature inventory;
- `plan`: supplies the ordered exact feature DAG and parameters;
- `executor`: bypasses the language model and replays the GT construction.

The paired contrasts have specific meanings:

- `Y(perception) - Y(normal)` estimates the error removed by exact geometric
  perception under the current Agent policy;
- `Y(plan) - Y(perception)` estimates the error removed by exact feature planning;
- `Y(executor) - Y(plan)` exposes model tool use or action-translation error;
- GT self-score failure invalidates model attribution and points first to data or
  verifier incompatibility.

These are controlled-system effects, not intrinsic properties of the base model.
For stochastic Agent conditions, use at least three paired replicates and report
each oracle condition separately from normal benchmark accuracy.

The ladder localizes a failed computational stage, not ownership inside that stage.
For example, perception-oracle success means the normal image-to-feature path is the
bottleneck; it does not by itself distinguish a weak Agent observation policy from a
base-model vision limitation. Ownership requires two further controls: keep the
model fixed and replace the perception policy, then keep the Agent fixed and replace
the model. Only the interaction of those contrasts supports an Agent-versus-model
claim.

## Static extraction

`gt-trajectory-extract` parses CadQuery source with Python's AST. It does not import
CadQuery and does not execute dataset code. It records sketch calls, extrusion
parameters, Boolean dependencies, final-solid checkpoints, source hashes, and two
hash-bound oracle packets. The perception packet removes source names and ordering;
the plan packet retains ordered DAG nodes but withholds executable source and GT CAD.

```powershell
python -m cad_evoloop.cli gt-trajectory-extract `
  .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  --output reports/generated/gt-trajectories-ortho2cad-40
```

## Oracle campaigns

Run the same frozen selection and `gpt-5.6-sol` configuration for each condition.
The campaign manifest records `durable-kernel-gt-oracle-perception-v1` or
`durable-kernel-gt-oracle-plan-v1`, the oracle manifest hash, and its level.

```powershell
python -m cad_evoloop.cli agent-geometry-batch MANIFEST SELECTION `
  --campaign ORACLE_CAMPAIGN `
  --oracle-context reports/generated/gt-trajectories-ortho2cad-40/oracle-context.json `
  --oracle-level perception
```

Oracle context is copied into the isolated sample project, registered as an
`evaluator_oracle` artifact, included in the run ledger, and embedded through the
same UTF-8 prompt channel on every repair turn. Oracle context cannot be combined
with human-review feedback in the same campaign.

## Replay and report

Executable replay is opt-in because it executes the dataset program. It only accepts
source and output paths inside the workspace, writes an instrumented copy, exports a
STEP checkpoint after every final-solid assignment, and records unavailable runtime
dependencies explicitly.

```powershell
python -m cad_evoloop.cli gt-trajectory-replay SOURCE.py TRUTH.step --output OUTPUT
python -m cad_evoloop.cli gt-attribution-report MANIFEST --sample SAMPLE `
  --output OUTPUT --normal-result NORMAL --perception-result PERCEPTION `
  --plan-result PLAN --executor-result OUTPUT/replay-result.json
```

The report contains the GT feature DAG, GT self-consistency score, condition scores,
the preregistered decision, and observational diagnostics from the normal trace.
Missing or unavailable interventions produce `not_identified`; they are not silently
treated as failed conditions.
