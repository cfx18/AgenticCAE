# EvoCAD Geometry Benchmarks

This directory defines the external, geometry-grounded datasets used by EvoCAD.
Downloaded assets stay below `.local/datasets/evocad/` and are not committed.

The pilot profile currently fetches:

- BenchCAD at dataset revision `5919f578ab09ec283603a082fab07c7639ab56eb`:
  all 17,900 code-generation rows, QA, and edit-benchmark Parquet files. The
  dataset card declares CC BY 4.0.
- Ortho2CAD Orthographic Drawings at dataset revision
  `5614e7e792635ab3121bcbb4a0bde0df19fb3b3d`: the inference and Fusion 360
  reconstruction subsets. The dataset card does not currently declare a
  license, so these files are evaluator-only and must not be redistributed.
- OmniMech official sample and code archives. The download URLs are not pinned
  to a published revision, so the generated SHA-256 manifest is authoritative
  for a local experiment. Do not redistribute them until release terms are
  confirmed.

Run from the repository root:

```powershell
python evals/geometry-benchmarks/scripts/fetch.py
```

The downloader supports resuming `.part` files and writes
`.local/datasets/evocad/download-manifest.json` after all requested artifacts
have passed size checks and SHA-256 hashing.

## Geometry protocol

Install the isolated geometry dependencies, materialize a pilot, and verify that
the STEP and STL ground truths agree before scoring agent output:

```powershell
pip install -e ".[geometry]"
cad-evoloop geometry-materialize --bench-count 10 --ortho-count 10 --omni-count 10
cad-evoloop geometry-calibrate .local/datasets/evocad/materialized/geometry-pilot-v1/manifest.json `
  --output .local/datasets/evocad/geometry-runs/calibration.json
```

The 50-sample strict split uses only sources with STEP ground truth:

```powershell
cad-evoloop geometry-materialize `
  --output .local/datasets/evocad/materialized/geometry-50-v1 `
  --bench-count 0 --ortho-count 40 --omni-count 10

cad-evoloop geometry-split `
  .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  --output evals/geometry-benchmarks/splits/geometry-50-split-v1.json
```

Protocol `evocad-geometry-v2` permits translation and the 24 right-handed axis
orientations, but never scale. Strict passage requires a watertight candidate,
voxel IoU at least 0.99, normalized symmetric Chamfer at most 0.006, mean
bounding-box relative error at most 0.002, and volume relative error at most
0.005. The older v1 thresholds are retained as the `acceptable` tier rather
than being reported as strict completion. Surface sampling defaults to 20,000
deterministic points. Both tiers are calibrated against ten STEP/STL pairs.

For native AutoCAD candidates, export and score without opening desktop
AutoCAD:

```powershell
cad-evoloop geometry-export candidate.dwg .local/datasets/evocad/runs/candidate.stl
cad-evoloop geometry-score .local/datasets/evocad/runs/candidate.stl ground_truth.step `
  --output .local/datasets/evocad/runs/score.json
```

Run a trajectory-recorded Codex/AutoCAD campaign. Ground-truth paths are not
staged into the agent directory; repair turns receive sanitized numerical
feedback. Each logical iteration is closed before another CAD action starts:
the agent edits, the harness verifies that exact candidate, and the same Codex
thread receives the verdict and records a structured `continue` or `stop`
decision. A `continue` decision must name a concrete geometry or recovery
change. Non-improvement is advisory evidence for that decision, not an
automatic stop. Strict passage, the job time budget, an unavailable decision,
and `--max-iterations` are external safety stops. The default safety ceiling is
12; the final iteration still receives feedback, so the record distinguishes
an agent stop from an agent that wanted to continue but was safety-limited.

```powershell
cad-evoloop geometry-batch `
  .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  --split-file evals/geometry-benchmarks/splits/geometry-50-split-v1.json `
  --split-name cost_pilot `
  --campaign geometry-cost-pilot-v2 `
  --max-iterations 12 `
  --model gpt-5.6-sol --model gpt-5.6-terra --model gpt-5.6-luna

cad-evoloop geometry-report evals/geometry-benchmarks/batch/geometry-cost-pilot-v2 `
  --output reports/generated/geometry-cost-pilot-v2 `
  --annotations evals/geometry-benchmarks/annotations/cost-pilot-v2-data-quality.json
```

Export the same frozen trajectories for expert review and start the local
workbench. This does not invoke the agent or AutoCAD. With `--render-geometry`,
the bundle includes hash-bound browser STL assets alongside deterministic PNG
fallbacks. The review workbench presents the complete input drawing at full
width and synchronized orthographic ground-truth, candidate, and overlay
viewports: rotating, panning, or zooming any geometry viewport updates all
three.

```powershell
cad-evoloop geometry-review-export `
  evals/geometry-benchmarks/batch/geometry-cost-pilot-v2 `
  --output reports/generated/geometry-cost-pilot-v2/review `
  --source-manifest .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  --annotations evals/geometry-benchmarks/annotations/cost-pilot-v2-data-quality.json `
  --render-geometry

cad-evoloop geometry-review-serve reports/generated/geometry-cost-pilot-v2/review `
  --reviews evals/geometry-benchmarks/human-reviews/geometry-cost-pilot-v2.jsonl
```

Human reviews distinguish agent geometry/reasoning failures from ambiguous
inputs, ground-truth defects, verifier metric or threshold defects, alignment,
export, MCP, harness, and attempt-selection failures. They also record possible
false positives and false negatives, evidence sufficiency, geometry fidelity,
verifier validity, reflection quality, recommended disposition, and structured
findings. The ledger is append-only and hash-chained; revisions retain the
superseded record. This makes disagreement with the verifier measurable instead
of silently changing benchmark annotations.

The report writes per-attempt data to `attempts.csv`, per-model aggregates to
`models.csv` and `summary.json`, optional filtered aggregates to
`models-primary.csv`, and 1600x900 repair-trajectory and model
comparison figures. `Pass@1` measures strict success without repair; `Strict
final` measures strict success after selecting the best repair checkpoint.
Elapsed time and token counts include every attempt. MCP and Core Console
failure counts are diagnostic events and do not imply that the enclosing run
failed, because the agent may recover with another tool call or repair attempt.
Human-audited benchmark defects are versioned separately under `annotations/`.
Samples marked `exclude_primary` remain in raw diagnostic reports but must not
be included in headline model-comparison metrics; `review` samples remain
eligible with their stated limitations disclosed.

The committed protocol and calibration JSON files preserve both v1 and v2.
Raw data remains local because not every upstream source has redistribution
terms. Campaign trajectories and binary candidates are also local and ignored;
their manifests bind sources, inputs, and ground truth by SHA-256.
Download, materialization, split, and campaign manifests are deterministic.

## Durable Agent Evaluation

The first long-horizon compatibility condition fixes the model to
`gpt-5.6-sol` and evaluates 30 unique dev/validation samples while retaining all
hidden-test samples for later use:

```powershell
cad-evoloop agent-geometry-batch `
  .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  evals/geometry-benchmarks/splits/geometry-30-devval-v1.json `
  --campaign agent-geometry-30-sol-v1 `
  --model gpt-5.6-sol --reasoning-effort medium
```

Use `--max-jobs 1` for an initial end-to-end smoke; rerunning the same command
without the limit resumes the immutable campaign and skips completed projects.

Each sample runs in an isolated event-sourced Project. The campaign manifest
binds the selection, model, execution settings, and hashes of every Agent,
prompt, skill, and protocol source. This compatibility condition must be
interpreted as a durability/parity experiment, not as a new modeling policy.
