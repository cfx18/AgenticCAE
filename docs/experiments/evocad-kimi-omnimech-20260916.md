# EvoCAD + Kimi K3: OmniMech 2, 4, 10

## Registration

- User requested the same three drawings with EvoCAD instead of native Kimi Code.
- Model: `kimi-k3`; thinking effort: `max`; local Kimi Code version: `0.43.1`.
- Harness: existing EvoCAD durable project kernel and geometry feedback loop v3.
- Kimi Code replaces the Codex action/conversation transport, not the outer loop.
- Reconstruction condition: baseline; no forced IR, human reviews, oracle features,
  manual mirror hints, or ground-truth geometry access.
- Feedback: each candidate's metrics, localized mismatches, native topology, tool
  diagnostics, and best-checkpoint state. The model makes continue/stop decisions
  in the same Kimi session; decisions are validated against the existing schema.
- Budget: 5,400 seconds per case, including action and feedback turns; 12 iterations
  are a safety ceiling. The first action reserves 540 seconds for decision retries.
- Native Kimi controls also used 5,400 seconds. The earlier EvoCAD/Astra trial used
  3,600 seconds, so it is not an equal-budget comparison with that trial.
- Verifier unchanged: 20,000 surface samples, voxel resolution 64; strict thresholds
  and right-handed rotation/translation alignment unchanged. No reflection/scale.

## Transport And Records

`src/cad_evoloop/agent/models/kimi_geometry.py` stages CLI requests in files and a
small Node launcher passes the complete prompt in-process, avoiding Windows argv
limits. Each job has its own Kimi session home and isolated AutoCAD MCP workspace.
The model sees the original EvoCAD prompts, plus the decision JSON schema where
the Codex adapter formerly supplied it as a CLI option. Kimi has no native schema
flag here; invalid responses use EvoCAD's existing transport retry mechanism.

Raw model events, exact prompts, MCP configuration (no API keys), session IDs,
transport errors, drawings, topology, verifier output, decisions, and ledger
hashes are retained. Kimi stream token usage is unavailable, not measured zero.

Campaign: `evals/geometry-benchmarks/batch/evocad-kimi-k3-omnimech-2-4-10-20260916`.
Its `trial-config.json` is the progress record; stdout/stderr logs remain beside it.
The runner is `evals/geometry-benchmarks/scripts/evo_kimi_trial.py`.

## Execution Policy

After transport smoke testing, run the queue in a hidden background process.
No conversational supervisor polls it. Cases execute in order 2, 4, 10. Results
are exported to separate immutable review bundles and added to the existing
catalog as `evocad-kimi-2`, `evocad-kimi-4`, and `evocad-kimi-10` under EvoCAD.
The expected local review server is refreshed after publication; an unrelated
process on port 8770 is never stopped. Errors are recorded in the progress file.

## Preflight

- 58 focused geometry-loop, campaign, review, and Kimi transport tests passed.
- Live two-turn Kimi smoke test passed: exact session resumption retained a
  synthetic memory token and produced schema-valid JSON on the second turn.
- Smoke artifacts: `.local/kimi-evocad-smoke/` (not evaluation samples).
