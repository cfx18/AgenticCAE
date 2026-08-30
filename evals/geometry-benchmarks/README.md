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

