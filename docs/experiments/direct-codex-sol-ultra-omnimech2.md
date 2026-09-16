# Native Codex Single-Case Trial: OmniMech 2

Date: 2026-09-14. Campaign: `direct-codex-sol-ultra-omnimech2-20260914`.

## Question

How well does a fresh native Codex conversation with `gpt-5.6-sol` and `ultra`
reconstruct the low-scoring `omnimech:2` case without EvoCAD's outer agent loop?
The case was selected from the user's active review page before execution.

## Execution Contract

- One fresh native Codex conversation; no externally injected repair turns.
- Explicit model `gpt-5.6-sol`, effort `ultra`, installed CLI
  `0.154.0-alpha.6.2`. No model substitution.
- Original full source drawing and original task, copied with SHA-256 binding.
- Same audited AutoCAD MCP/Core Console interface and editable DWG requirement.
- No forced IR, specialist preprocessing, prior candidates, human feedback,
  or ground-truth scoring during model execution.
- The native conversation may plan, inspect, construct, and revise autonomously.
  One submitted attempt does not mean one internal tool call or one CAD job.
- 3,600-second wall-time safety ceiling, not a prescribed reasoning/repair count.
- Final DWG independently exported and scored using geometry-v2: 20,000 surface
  samples, 64-voxel resolution, original alignment and strict thresholds.
- JSONL Codex events, MCP audit, prompt, command, final answer, input hashes,
  immutable ledger snapshots, final mesh and verdict retained in the workspace.
- Source-only staging is a prompt-level read restriction, not OS-level secrecy.
  Inspect the observable tool audit for contamination before interpreting results.

## Historical Comparators

`agent-geometry-30-sol-v2`: Sol medium, 12 externally scheduled attempts,
sum of recorded attempt elapsed times 1,820.975 seconds. Selected score **66.43**,
IoU **0.747455**, normalized Chamfer **0.013929**, bounding-box error **0**,
volume error **0.000108**. Strict fail; stopped at max iterations.

`agent-geometry-30-sol-native-feedback-v3`: Sol medium, 10 externally scheduled
attempts, sum of recorded elapsed times 2,557.992 seconds. Selected score **72.92**,
IoU **0.802343**, normalized Chamfer **0.010906**, bounding-box error **0**,
volume error **0.004266**. Strict fail; agent chose to stop.

Both historical runs received evaluator feedback. Harness, reasoning effort,
feedback access, CLI version, and time budget are not controlled between these
conditions. This is a single-case capability probe, not a causal harness ablation
or evidence of a benchmark-wide improvement.

The frozen verifier reports a non-watertight tessellation for this case's GT STEP.
Preserve the existing evaluator for this comparison; do not silently repair or
change GT. The reference caveat must remain visible when reporting precision.

## Artifacts

Runner: `evals/geometry-benchmarks/scripts/direct_codex_trial.py`.

Campaign: `evals/geometry-benchmarks/batch/direct-codex-sol-ultra-omnimech2-20260914`.

The authoritative lifecycle and result pointer are in `trial-config.json`.
Final metrics must be taken from the persisted verdict, not agent self-report.

## Transport Failure and Retry

The default-transport run was interrupted after 1,122.298 seconds of repeated
WebSocket failures (Windows errors 10053/10054), with no candidate DWG and no
AutoCAD modeling job. Codex had read the task and created detail crops, including
recovering from an unavailable ImageMagick executable by using System.Drawing.
The missing-output score of 0 is a sentinel, not a geometry measurement. Exclude
this run from geometry capability comparisons; usage is unknown, not zero.
The original artifacts and ledger were preserved, with an explicit
`infrastructure-disposition.json` sidecar explaining operator termination.

The fresh retry is `direct-codex-sol-ultra-omnimech2-https-20260914`. Only transport
configuration changed: a CLI-scoped provider using the same official
`https://chatgpt.com/backend-api/codex` endpoint, existing OpenAI authentication,
Responses wire API, and `supports_websockets=false`. The model and effort remain
`gpt-5.6-sol` / `ultra`. No global configuration or credential was modified.
The relevant provider fields are documented in the
[official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Preparation and related regression coverage: 42 tests passed. Following the
transport-option addition, the six direct-trial/provider tests passed again.

## Completed Result

The HTTPS run completed voluntarily after **1,679.828 seconds (28.0 minutes)**,
without hitting the 3,600-second ceiling. No evaluator feedback was injected.
It generated exactly one native editable solid, passed AutoCAD AUDIT, and exported
70 native faces / 163 edges without topology export errors.

- Composite score: **63.34 / 100**. Strict result: **fail**.
- Voxel IoU: **0.878517**, compared with V2 **0.747455** and V3 **0.802343**.
- Normalized Chamfer: **0.009053**, versus V2 **0.013929** and V3 **0.010906**.
- Bounding-box relative error: **0**, as in both historical comparators.
- Volume relative error: **0.051968 (5.1968%)**, versus V2 **0.0108%** and V3 **0.4266%**.
- Candidate volume: **27,109.027039**; frozen reference volume: **25,769.814542**.
- Candidate mesh watertight: **true**. Surface-area relative error: **1.3727%**.

The continuous score allocates 35 points to IoU, 25 to Chamfer, 15 to bounds,
20 to volume and 5 to watertightness. The volume component clips to zero at
1% error, so the new run loses all 20 volume points. It improves overlap and
surface distance while scoring lower overall. This metric tradeoff is real;
do not collapse it into an unqualified "better harness" or "worse model" claim.
Strict passage still fails IoU >= 0.99, Chamfer <= 0.006, and volume error <= 0.005.

## Observed Native Workflow

The requested ultra configuration autonomously launched three auxiliary tasks:
`drawing_dims`, `cad_strategy`, and `drawing_audit`. The experiment runner did
not create or schedule these helpers. The main conversation independently:

1. Cropped supplied views and examined the enlarged drawings.
2. Constructed the stepped rail body, mounting ears, window and drilling features.
3. Exported native topology and checked the actual bounds and surface types.
4. Re-read the crowded dimensions, shifted the window and cross-hole stations
   by 0.5 mm, and rebuilt the part without seeing a GT score.
5. Exported STL, rendered four views with trimesh/matplotlib, and inspected them.
6. Ran final AUDIT and exported fresh native topology before voluntarily stopping.

There were two geometry construction versions, an STL-export job and a final
audit/save job. The single `a001` result represents one continuous conversation,
not a one-action restriction. Its self-checks did not catch the remaining GT
geometry discrepancies. The final message acknowledged ambiguity in stepped
reliefs and opposed M4-hole termination, but underestimated the remaining error.

CLI-reported completed-turn usage: 2,040,208 input tokens, 1,937,024 cached input
tokens, 26,607 output tokens, including 17,391 reasoning-output tokens. This is
the provider-reported usage scope, not a separately verified total across every
native helper. The interrupted first run has no completed-turn usage report.

The root CLI event export omits some native helper and image-view events.
Supplementary public-action snapshots are retained in
`reports/generated/direct-codex-sol-ultra-omnimech2-https-20260914-public-traces`.
Reasoning items were excluded; these are public actions/messages, not private
chain-of-thought. The app's notLoaded/interrupted display for CLI-owned runs is
not used as the experiment's execution status.

Review bundle:
`reports/generated/direct-codex-sol-ultra-omnimech2-https-20260914-review`.
Serve it with `powershell -NoProfile -ExecutionPolicy Bypass -File
apps/geometry-review/start-review.ps1 -View direct`, then open
`http://127.0.0.1:8770/`. The old review services remain unchanged.

## Interpretation

Direct Codex plus Sol ultra improved this case's shape reconstruction, but did
not solve it accurately enough for strict passage. Native autonomy and an
explicit preprocessing helper emerged without a forced IR schema. They did not
provide a reliable independent correctness signal. A matched follow-up would
keep effort and budgets fixed and expose the same verifier as an optional tool,
with Codex deciding when to call it; this follow-up has **not** been run.
