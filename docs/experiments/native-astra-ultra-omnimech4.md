# Native Astra Ultra: OmniMech 4

Requested on 2026-09-14 after the OmniMech 2 mirror diagnostic. This is a new
autonomous reconstruction from the source drawing, not a mirror repair and not
a continuation with GT feedback.

## Registration

- Campaign: `direct-codex-astra-ultra-omnimech4-https-20260914`.
- Sample: `omnimech:4`; model: `gpt-6-astra`; reasoning effort: `ultra`.
- Native Codex CLI `0.154.0-alpha.6.2`, same installed executable as OmniMech 2/10.
- One fresh continuous conversation, unchanged `direct_codex_trial.py` prompt,
  HTTPS transport using the signed-in Codex account, audited AutoCAD MCP.
- Source-only staging and prompt restriction, not an OS read-isolation claim.
- No forced IR, external repair turn, source-solution access, mirror hint or
  ground-truth scoring tool during the modeling run.
- Isolated AutoCAD Core Console jobs; 3,600-second model-run safety timeout.
- Held-out geometry-v2 scoring after the run: 20,000 samples, voxel resolution 64.
- Input-image SHA: `74b4cb73e73a20c7647c3c4dab2479a69308887814bc1fb99f127165cad88e97`.
- Root public task: `01a0a08a-39df-7723-8f65-0c08549d23f7`.
- Preflight: ordinary account usage allowed; 5% weekly allowance remaining.
  No reset credit used or authorized; no separately billed model API.

## Status

Completed normally in **914.472 seconds** (15.2 minutes), return code 0,
no timeout or external intervention during modeling. Authoritative execution state:
`evals/geometry-benchmarks/batch/direct-codex-astra-ultra-omnimech4-https-20260914/trial-config.json`.

## Result

- Score **100.0**, strict **pass**, IoU **0.993030**.
- Normalized Chamfer **0.003613**; raw Chamfer **0.532162**.
- Bounding-box relative error **0.000376** (0.0376%); volume relative error
  **0.004666** (0.4666%); surface-area relative error **0.002468** (0.2468%).
- Watertight candidate; all five strict checks pass. No sampled surface regions
  exceed the current localization threshold.
- One final native Solid3d; topology export has no errors, native volume
  **86400.2704538483 mm3**, bounds `[-51.1149296,-51.1149296,0]` to
  `[51.1149296,51.1149296,28]`.
- Root CLI usage: 986,775 input tokens (931,328 cached), 13,011 output tokens.
  This is the CLI's recorded usage, not a separate billing calculation.

This is the original autonomous result, not a post-hoc mirror result. The agent
constructed a revolved envelope, hub/bore/keyway/radial holes, then 24 repeated
tooth profiles. It inspected topology, a watertight mesh, axial sections and a
source-image silhouette overlay before deciding to retain the tooth profile.
The public construction record and four intermediate DWGs are archived.

The agent explicitly disclosed assumptions: 28 mm overall length inferred from
the undimensioned section; M6 threads modeled as smooth nominal openings; small
undimensioned edge treatments approximated. A score of 100 means passing these
capped metrics, not exact geometry or manufacturing certification. In particular,
volume error 0.4666% is close to the 0.5% strict threshold.

## Review And Integrity

- [Interactive result](http://127.0.0.1:8770/?view=direct-astra-4): Harness **Codex**,
  experiment **OmniMech 4 - Astra Ultra**.
- Candidate SHA: `c5e43c9b1d958e0dd8d08f31b37f13e6678137d4a488f4d48d73356afc5c8720`.
- GT SHA: `1e70176e66c216c17093806f7f0391695d66298245a2166976620022bd3087dd`.
- Review bundle SHA: `e06e9bf944cbf7814c950114c3c87efd6bb2d845ae82ad439268c0b9391ed1f5`.
- Completed-run ledger initially verified 41 files / 25 events. After archiving
  27 work products and evaluator diagnostics, it verifies 68 files / 53 events;
  see campaign `postrun-integrity.json` for the later audit. Original completed
  result is retained, including its original point-in-time integrity count.
- Final topology is supplemental evaluator evidence produced after the model
  finished, not a check falsely attributed to the agent. Agent stage03 topology
  remains separately identifiable as intermediate evidence.
- Browser verified complete input, nonblank geometry, linked dragging and correct
  model/sample/score binding; no error or warning messages. No test human reviews
  were submitted. The existing ledgers and frozen historical bundles are unchanged.

## Post-Run Export Incident

While adding final topology evidence, Core Console rewrote the submitted DWG
despite the export's read-only intent. A before/after SHA check caught this after
scoring had completed. The altered file, first topology export and incident record
were retained under the job's `evaluator-export-side-effect/` directory. The
submission was restored byte-for-byte from the already-scored `candidate.dwg`
copy and verified against the completed result and ledger hash. Score and scored
STL were not changed or rerun; this is an evaluator-side incident, not an agent
modeling failure.

`TopologyExportJobManager` now copies its input to the workspace job directory
before starting Core Console and records both original and working paths. A fresh
export verified the original input remained unchanged. Its topology `source_dwg`
names the actual working copy; `evaluator-topology-export.json` binds that job to
the original candidate hash. The source code fix is post-run and was not present
in, or fed back to, this modeling conversation.

Regression checks: 32 Python tests passed, including a simulated Core Console
input-rewrite test, feature-backfill compatibility, native CLI and review tests.

## Historical Context

The feature-review V2 bundle has an EvoCAD / Sol medium result of 99.4,
strict fail, IoU 0.972953, normalized Chamfer 0.004202, bounding-box error
0.000631, volume error 0.000594 and surface-area error 0.00896.
This is contextual only: model, effort, harness, feedback access and potentially
other protocol parameters differ. It is not a harness-only ablation or a fair
single-variable model comparison. Neither that output nor its score is supplied
to this Astra conversation.
