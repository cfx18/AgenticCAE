# Reconstruction IR Ablation

EvoCAD separates image interpretation from CAD execution with a persisted,
provider-neutral reconstruction intermediate representation (IR).

## Stage boundary

```text
orthographic images
  -> IR Builder
  -> schema and reference gate
  -> reconstruction-ir.json
  -> CAD execution Agent
  -> AutoCAD MCP
  -> geometry verifier
```

The IR records views, drawing elements, observed/inferred/assumed dimensions,
cross-view correspondences, feature hypotheses, constraints, construction
hypotheses, alternatives, ambiguities, and confidence. `operation` and
`geometry` deliberately remain open fields. The IR does not restrict which
AutoCAD or AutoLISP operations the execution Agent may use.

## Conditions

- `baseline`: the CAD Agent receives the original images and no IR gate.
- `forced_ir`: the same model thread must produce a valid IR before gaining
  AutoCAD tools. Its image context remains available.
- `specialist_ir`: an independent same-model thread builds the IR. The CAD
  Agent runs in an image-free workspace and receives only the IR.
- `oracle_ir`: an unordered exact-feature perception oracle is translated to
  the same IR. The CAD Agent receives no images. This condition is
  evaluation-only and is excluded from normal accuracy.

The preregistered comparison is in
`evals/geometry-benchmarks/ir-ablation-v1.json`.

## Artifacts

Each non-baseline job persists:

- `ir-builder/reconstruction-ir.json`
- `ir-builder/ir-validation.json`
- `ir-builder/ir-build-record.json`
- `ir-builder/provider-turns/` with prompts, events, stderr, and final output
- `ir-builder/rejected-ir-*.txt` for structurally invalid generations

These files are copied into the run ledger and registered in the durable
project store. The build record binds the model conversation, usage, validation
errors, and accepted IR digest.

## Run

Use a distinct immutable campaign ID for every condition:

```powershell
python -m cad_evoloop.cli agent-geometry-batch MANIFEST SELECTION `
  --campaign ir-forced-r1 --model gpt-5.6-sol `
  --reconstruction-mode forced_ir

python -m cad_evoloop.cli agent-geometry-batch MANIFEST SELECTION `
  --campaign ir-specialist-r1 --model gpt-5.6-sol `
  --reconstruction-mode specialist_ir

python -m cad_evoloop.cli agent-geometry-batch MANIFEST SELECTION `
  --campaign ir-oracle-r1 --model gpt-5.6-sol `
  --reconstruction-mode oracle_ir `
  --oracle-context ORACLE_CONTEXT --oracle-level perception
```

Run paired stochastic replicates before making a causal claim. A single sample
is suitable for integration testing and trajectory diagnosis only.

## Integration result

The first four-condition diagnostic for `ortho2cad:00186338` is frozen at
`evals/geometry-benchmarks/reference-runs/reconstruction-ir-ablation-00186338-r1.json`.
The specialist condition reached `99.95` in seven attempts and stopped by its
own evidence test; the exact unordered oracle IR passed strictly in one
attempt. The forced same-thread condition did not beat the historical
baseline. These results support a larger paired evaluation of perception
specialization, but are not a population-level causal claim.
