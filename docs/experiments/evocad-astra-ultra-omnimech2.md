# EvoCAD + Astra Ultra: OmniMech 2

Requested on 2026-09-15. New baseline EvoCAD reconstruction from the original
drawing, separate from the earlier native Codex trial and human mirror repair.

## Registered Conditions

- Campaign: `evocad-astra-ultra-omnimech2-https-20260915`.
- Model: `gpt-6-astra`; effort: `ultra`; sample: `omnimech:2` only.
- EvoCAD durable kernel, baseline reconstruction, current Boolean lineage and
  geometry feedback loop. No forced/specialist IR, oracle packet, human review
  packet, prior candidate or manual mirror hint.
- Original drawing SHA: `fef27d4171b22c08156d694224383ccae3dae7e5fc998ee880f7613c7692bef6`.
- Same installed Codex CLI `0.154.0-alpha.6.2` used as the model execution provider.
  The harness orchestration and action/feedback scheduling are EvoCAD, not the
  native single-conversation benchmark prompt.
- HTTPS transport with the same signed-in account. Scoped command-builder
  overrides apply to both fresh action and resumed feedback turns; recorded in
  the launcher and each generated command. No global Codex settings changed.
- Model action timeout 1800 seconds; total job budget 3600 seconds; maximum 12
  iterations as a safety limit; stagnation limit 2 is advisory. The longer action
  timeout avoids truncating Ultra at the historical 900-second default.
- Frozen geometry-v2 scoring: 20,000 surface samples / voxel resolution 64.
  Unlike the native control, EvoCAD returns verifier scores and localized geometry
  evidence during the run. Raw evaluator CAD and prior solutions are not inputs.
- Initial model conversation: `01a0a2f3-1ee8-74e2-afdb-a966eac7b35d`.
- Account preflight: ordinary usage allowed; 2% weekly allowance remaining.
  No reset credit authorized or consumed. A quota/transport interruption must
  be distinguished from an agent geometry failure.

## Status

Completed at `2026-09-15T03:10:27.545Z`. First and selected attempt `a001` scored
100.0 and passed all strict checks. Authoritative state and frozen selection are in the campaign's
`trial-config.json`, `selection.json` and `agent-campaign-manifest.json`.
The launcher is `evals/geometry-benchmarks/scripts/evo_astra_omnimech2_trial.py`.
It changes transport only, not the existing EvoCAD loop, prompts, decisions or
verifier thresholds. First-attempt and selected/final metrics must be retained
separately when reporting results.

### Supervisor Interruption

After a host tool interruption during the progress-query turn, process inspection
found neither the trial runner nor its model process alive, although the cached
trial status still said running. Stage01 body, stage02 front channel and stage03
rear channel were intact. No score had yet been produced.

At `2026-09-15T02:58:39.839Z`, the supervisor restored the conversation ID from
the interrupted public event stream to the recovery runtime and resumed the
existing durable project using `resume_evo_astra_trial.py`, as an independent
hidden background process. It uses the same model conversation
`01a0a2f3-1ee8-74e2-afdb-a966eac7b35d` and the same baseline prompt. There was no
manual geometry correction or GT hint. The resumed agent explicitly continued
from its staged model and produced stage04 window.

Prior traces are preserved under `attempts/a001/action-interruptions/i001/`.
Supervisor snapshots and incident metadata are in `supervisor-recovery/`.
This is an interrupted/resumed trial, not a pristine uninterrupted timing sample.
The existing harness resets its per-invocation job clock during recovery, so
interrupted wall time is additional to the resumed 3600-second budget and must
be reported separately. The incomplete pre-interruption call has no final usage
summary; completed-turn token totals must not be presented as full trial usage.

## Result

- One scored candidate, one successful post-verifier decision; no geometry repair
  round and no decision transport retry. The Agent chose `stop` / `can_improve=false`
  because no evidence-grounded change offered a plausible score gain. The recorded
  stop reason is `strict_pass`, not an iteration or time limit.
- Score: 100.0; voxel IoU: 1.000000; normalized Chamfer: 0.004563.
- Bounding-box relative error: 0; volume relative error: 0.000483 (0.0483%);
  surface-area relative error: 0.000550 (0.0550%); watertight: true.
- One native solid, 75 faces, 177 adjacency links. No surface region exceeded the
  fixed localization threshold. Alignment used identity rotation and translation,
  without scaling or reflection.
- The Agent represented threads using tap-drill bores and unspecified blind-hole
  tips as flat bottoms. Strict pass is a thresholded geometric result, not a claim
  of exact geometry or manufacturing validation.
- Resumed attempt elapsed: 705.036 seconds (the review UI's elapsed field).
  Initial launch to completion: 1594.503 seconds, about 26.6 minutes, including
  interruption/recovery. This is not a clean timing comparison.
- Raw CLI action counters: 1,119,464 input / 11,322 output; resumed decision
  counters: 1,187,505 input / 11,915 output. The latter appear cumulative within
  the conversation. The harness sum is preserved as raw output but is not a
  validated per-turn or billable-token total; interrupted usage is also incomplete.

### Evidence And Review

- Review: `http://127.0.0.1:8770/?view=evocad-astra-2`, under Harness `EvoCAD`.
  Original native Codex and human mirror diagnostic entries remain separate.
- Review bundle SHA:
  `05dfd8b34b9325a41a3cfb75487281455a5a4282046bf00ff3b9aa64fec263e1`.
- Scored DWG SHA:
  `2f0a827fe46b20ae2bdb16466e30953501b28666c1a401dba9a0a706be6067bd`.
- GT SHA: `beec5dbcffa47608dd0082b0185b46b127c67b3e37be5868c6d01e95df299889`.
- Durable project integrity: 16 events, 6 artifacts, snapshot/hash chain valid.
  Postrun ledger integrity: 218 files / 214 events, no errors. The original
  completed-result integrity snapshot remains unchanged at 47 files / 42 events.
- Additional archive: 171 artifacts, including twelve staged DWGs, thirteen native
  Core Console job directories, interrupted public/MCP traces, recovery metadata,
  frozen registration and supervisor sources. See `postrun-integrity.json` and
  `archive_evo_astra_trial.py`.
- Browser validation: correct Astra/Ultra binding and score, complete input image,
  three nonblank 3D views, synchronized drag rotation and no console warnings/errors.
  No synthetic human review was submitted.

### Recorded I/O Export

At the user's request, the completed trial was exported without another model/CAD
execution to `reports/generated/evocad-astra-omnimech2-recorded-io-20260915/` and
the adjacent `.zip` (6,499,812 bytes). ZIP SHA:
`d62ab1abed5551b86450e2ab557d72434532bc817726616e61a846020d8cc0b5`.
The package has 460 files, 109 CLI events, 113 normalized timeline records,
8 public Agent messages, 18 completed command executions, 28 audited MCP calls
and 13 native CAD jobs. It includes the interrupted action; duplicated reflection
compatibility streams remain in raw files but are not double-counted.

`transcript.md` contains saved prompts and CLI-emitted events. `mcp-calls.jsonl`
contains exact audit arguments/results. `autocad/` is numbered by native-job
submission order and includes submitted Lisp, actual payload/wrapper scripts,
native stdout/stderr and before/after topology. `raw/` preserves campaign and
ledger evidence byte-for-byte; `manifest.json` indexes exported files by SHA-256.
The five focused export tests passed, as did the 32 trial/topology/review/report
regression tests. Export warnings: none; ZIP CRC check passed.

The execution path is EvoCAD's outer task/verifier/reflection loop, then Codex
CLI's inner model/tool loop with Astra, then audited AutoCAD MCP, then isolated
`accoreconsole.exe` executing AutoLISP. This is not a direct paid model API provider
and not mouse-based AutoCAD control. Agent-selected shell commands also read
tool-generated files and return those observations through Codex.

Completeness is limited to locally captured I/O. Model-service internal prompts,
private reasoning, serialized HTTP requests, internal image tokenization and any
already-truncated tool output cannot be reconstructed. CLI events lack absolute
timestamps, so normalized order uses explicit phases and original stream lines,
not invented cross-stream timing. Native logs are available evidence, not proof
that all their contents were read by the Agent. See actual command outputs for
what was returned to the model.

## Comparison Boundaries

Native Codex + Astra Ultra on this sample scored 91.69, strict fail, IoU 0.890819,
in 929.209 seconds. The later human-requested whole-solid mirror scored 100 and
IoU 1, but is not an autonomous result and is excluded from the primary control.

The observed selected-score difference is +8.31 points and strict fail becomes
strict pass. This EvoCAD reconstruction passed before receiving its first score:
it is evidence of a successful first candidate under this configuration, not
evidence that low-score reflection repaired the earlier native candidate.

This is a single-case comparison of the two current harness configurations, not
a statistical ranking or a feedback-controlled harness-only ablation. EvoCAD's
in-run GT-derived feedback, prompting and action/decision boundaries differ;
both use the same model, effort label, input and final scoring settings.
The topology-export input-copy fix made after the earlier native trials is
present here; it protects artifacts without changing geometric operations.
