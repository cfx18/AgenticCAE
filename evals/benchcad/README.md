# BenchCAD evaluation

This adapter keeps the Agent-visible image-feedback loop separate from hidden
ground-truth scoring. The Agent sees only the four rendered views, its CadQuery
program, execution errors, and an image-only silhouette comparison. Ground-truth
STEP and code paths are passed to BenchCAD's scorer only after explicit submit.

The pinned upstream agentic harness revision used during development is
`dfe51280de93adfba9b233d89bc32dfb223a22f9` (PR #53). The pinned Hugging Face
dataset revision is `5919f578ab09ec283603a082fab07c7639ab56eb`.

```powershell
python -m cad_evoloop.cli benchcad-materialize --count 30
python -m cad_evoloop.cli benchcad-agent-batch `
  --data-dir .local/benchcad-eval/family-30-v1 `
  --campaign sol-family-30-v1 --model gpt-5.6-sol `
  --reasoning-effort medium --max-records 30 --max-iterations 12
python -m cad_evoloop.cli benchcad-report `
  reports/generated/benchcad/sol-family-30-v1 `
  --data-dir .local/benchcad-eval/family-30-v1 `
  --upstream .local/benchcad-agentic --workers 4
```

`benchcad-report` scores every archived checkpoint after the Agent has stopped.
Those hidden GT measurements are marked evaluator-only and are never fed back
to the Agent. The command caches per-record scores and writes `analysis.json`,
`cases.csv`, `summary.md`, and PNG/PDF paper figures into the campaign folder.

Without Docker these runs are labeled `local-audited-process-pilot`. Their
official final scores use BenchCAD's implementation, but host process isolation
is not equivalent to the official container condition.
