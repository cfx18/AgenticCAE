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

Protocol `evocad-geometry-v1` permits translation and the 24 right-handed axis
orientations, but never scale. Strict passage requires a watertight candidate,
voxel IoU at least 0.95, normalized symmetric Chamfer at most 0.01, mean
bounding-box relative error at most 0.01, and volume relative error at most
0.02. Surface sampling defaults to 20,000 deterministic points.

For native AutoCAD candidates, export and score without opening desktop
AutoCAD:

```powershell
cad-evoloop geometry-export candidate.dwg .local/datasets/evocad/runs/candidate.stl
cad-evoloop geometry-score .local/datasets/evocad/runs/candidate.stl ground_truth.step `
  --output .local/datasets/evocad/runs/score.json
```

The committed `protocol-v1.json` is the machine-readable metric definition.
`calibration-v1.json` records the reference cross-format calibration; raw data
remains local because not every upstream source has redistribution terms.
