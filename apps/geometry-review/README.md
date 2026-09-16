# EvoCAD Geometry Review Workbench

CADGenBench 111 is available as `?view=cadgenbench-astra-111` and in
`astra.html?run=cadgenbench-astra-111`. Its official scores are pending; the HTML
compares published same-fixture reference results without substituting local
validity checks for GT accuracy. The Astra page includes DWG/SAT/STEP and the
prepared single-fixture submission ZIP. Official upload requires HF login.

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

## Harness Navigation

The upper-left Harness and Experiment selectors browse EvoCAD and native Codex
results on one origin, without reloading the page. Start the unified view:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/geometry-review/start-review.ps1 -View direct
```

Open `http://127.0.0.1:8770/`. The existing `8765` entry point also supports
the selector. `?view=direct`, `?view=features`, and the other catalog IDs select
an experiment directly and survive refresh. Switching preserves the current
sample when present, otherwise returning to the last selection in that experiment.
Unsaved review drafts are scoped to bundle/target/attempt in session storage;
they are not submitted to the human-review ledger until Save is clicked.

The sidebar separates experiment selection, optional filters, and the case list.
Filters and evaluation statistics start collapsed; active filters show a count
and can be reset together. Long selected experiment/model names wrap without
changing the native select's keyboard behavior. On narrow screens only the case
list scrolls independently, so expanded filters are not clipped.

The archive button groups standalone execution records by harness. The selected
experiment gets a contextual link only when its own export exists. Astra links
use the catalog's recorded-I/O model and exact experiment ID; Kimi's frozen
supplemental exports are explicitly bound in `VISION_RECORDS` in `app.js`.
Register new Kimi exports in both that mapping and `catalog.json` supplemental
pages. The shared Lucide runtime is vendored and included in new UI snapshots.

`catalog.json` explicitly registers each harness, experiment, frozen bundle and
independent review ledger. Add future exported campaigns there; do not relabel
different experiments as the same run or combine their ledgers. Paths must stay
inside the configured workspace. The launcher supplies `--catalog` to the review
server; omitting that flag retains legacy single-bundle behavior.

Catalog mode snapshots the shared navigation app under
`reports/generated/geometry-review-ui/<sha>/app`. It leaves every original bundle,
evidence hash, score and review line untouched. New reviews retain their original
evidence binding and additionally record a hash-bound `presentation` identifying
the actual shared UI and catalog used by the reviewer. The UI snapshot is verified
at startup and before a save. Scoped data, asset and review routes prevent
cross-experiment mixing; saves reject stale bundle/presentation identities.

The three existing reviews remain in **EvoCAD > V2 - Original reviews (30)**.
The feature-backfilled V2 view has its own evidence identity and ledger.
The two-sample human-feedback V3 experiment is not a complete V3 campaign.
Changing the navigation app requires restarting its server, creating a new
presentation snapshot. A still-running legacy server is reported explicitly by
the launcher and is never killed automatically.

Validation:

```powershell
.local/geometry-env/Scripts/python.exe -m pytest tests/test_geometry_review.py -q
node --test tests/geometry-review-navigation.test.cjs
node tests/geometry-review-sidebar-browser.cjs
```

The browser regression uses Playwright/Chrome and the running `8770` catalog.
It never submits reviews. Set `REVIEW_SOURCE=1` to preview working-tree UI assets
against existing evidence before restarting; omit it to test the deployed UI.

## Historical Entry Points

To restore the existing frozen review pages after a restart, run from the project:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/geometry-review/start-review.ps1 -All
```

This starts loopback-only, hidden background servers using the workspace geometry
runtime. It verifies the served bundle identity, reuses matching live servers, and
does not stop other processes or regenerate evidence. Logs are saved under
`.local/logs/review-*.log`. Without `-All`, it starts the feature-localization page;
use `-View main`, `-View lineage`, `-View recovery`, or `-View feedback` for
individual historical pages.

- Port 8765: the same Sol V2 candidates with native feature backfill and corrected
  camera initialization. Recommended for geometry browsing. It has a separate
  evidence identity and review ledger; the three original reviews stay at 8766.
  The UI-only derivative is `agent-geometry-30-sol-v2-feature-review-display-v2`;
  it retains all scores and cached assets from the historical feature-backfill
  bundle. It is not a new modeling run or the native-feedback V3 campaign.
- Port 8766: original 30-sample Sol V2 evidence and existing human review ledger.
  Its frozen viewer predates the camera initialization fix; use 8765 for geometry.
- Port 8767: two-sample Boolean-lineage V2 diagnostic.
- Port 8768: single-sample lineage recovery diagnostic.
- Port 8769: two-sample human-feedback intervention.
- Port 8770: native Codex with Sol ultra, `omnimech:2` (one run).

These pages are different frozen experiments, not interchangeable versions of
the latest score. Baseline BenchCAD results are separate from these AutoCAD pages.
The servers survive the launching shell, but must be restarted after a reboot;
this script does not install a system service or scheduled task.
`-ExecutionPolicy Bypass` applies only to the launching PowerShell process; it does
not modify the machine's execution policy.

Validate the hash chain and summarize active adjudications:

```powershell
cad-evoloop geometry-review-verify `
  reports/generated/geometry-cost-pilot-v2/review/review-data.json `
  evals/geometry-benchmarks/human-reviews/geometry-cost-pilot-v2.jsonl
```

The workbench displays recorded reflection and public trajectory messages, not
private model chain-of-thought. Raw human review ledgers are research data and
should be versioned after checking reviewer consent and de-identification.
# Astra Recorded I/O

Open `/astra.html` or the sidebar's **Astra execution records** link for all four
completed Astra model runs and the separate human mirror diagnostic. This page
shows saved prompts, public messages, tool returns, ordered native CAD scripts,
logs and manifest-indexed files without rerunning the model or AutoCAD.

Exports are registered through `recorded_io` in `catalog.json`, with SHA-bound
manifests and ZIPs. The read-only download routes serve only listed files and do
not expose the workspace as a general file server. Historical review bundles and
human-review ledgers remain unchanged. See `docs/ASTRA_RECORDS.md` for the inventory
and evidence-completeness limits.
