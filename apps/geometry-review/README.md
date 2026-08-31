# EvoCAD Geometry Review Workbench

This local workbench lets CAD experts adjudicate geometry campaigns without
redrawing candidates. It presents the agent-visible input, evaluator-only
ground truth, every candidate checkpoint, aligned overlays, verifier thresholds,
recorded reflections, public agent messages, and MCP audit events.

Generate a bundle with the geometry environment:

```powershell
cad-evoloop geometry-review-export `
  evals/geometry-benchmarks/batch/geometry-cost-pilot-v2 `
  --output reports/generated/geometry-cost-pilot-v2/review `
  --source-manifest .local/datasets/evocad/materialized/geometry-50-v1/manifest.json `
  --annotations evals/geometry-benchmarks/annotations/cost-pilot-v2-data-quality.json `
  --render-geometry
```

Serve it on loopback with an append-only review ledger:

```powershell
cad-evoloop geometry-review-serve `
  reports/generated/geometry-cost-pilot-v2/review `
  --reviews evals/geometry-benchmarks/human-reviews/geometry-cost-pilot-v2.jsonl
```

Open `http://127.0.0.1:8766/`. Review records are bound to the bundle,
campaign manifest, source manifest, protocol, sample, model, attempt, candidate,
verifier, input-image, render-image, and review-system hashes. The exporter
snapshots the served UI and review implementation into the bundle; the server
will not substitute the current working-tree UI. A correction creates a new record with
`supersedes_review_id`; it never edits the old line.

Validate the hash chain and summarize active adjudications:

```powershell
cad-evoloop geometry-review-verify `
  reports/generated/geometry-cost-pilot-v2/review/review-data.json `
  evals/geometry-benchmarks/human-reviews/geometry-cost-pilot-v2.jsonl
```

The workbench displays recorded reflection and public trajectory messages, not
private model chain-of-thought. Raw human review ledgers are research data and
should be versioned after checking reviewer consent and de-identification.
