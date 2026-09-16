# CADGenBench 111: Native Codex + Astra Ultra + Local AutoCAD

Requested 2026-09-16. Use the user's installed AutoCAD, not CadQuery/build123d.

## Registration

- Campaign: `cadgenbench-111-codex-astra-ultra-autocad-20260916`.
- Dataset: HuggingAI4Engineering/cadgenbench-data, generation fixture 111.
- Frozen dataset revision: `f76f965585817c621d6ea0d150d745adf670e66e`.
- Original input image SHA256: `51268794bc3e92bfaa6f822d34105ffa21bf2b691f1fa1b837f8c9f1a88c84e3`.
- Original description SHA256: `f8e7570f01656fafac2586b85fe3a5e470566610fc907dc93b135a0d6cb66ac1`.
- Model: `gpt-6-astra`; requested reasoning effort: `ultra`.
- Native Codex continuous conversation through the signed-in account, HTTPS.
- Audited AutoCAD MCP, isolated jobs in the local AutoCAD Core Console.
- No geometry-specific human preprocessing, forced IR, external repair loop,
  prior candidate, GT geometry, or benchmark-score feedback to the model.
- 5,400-second wall-clock safety backstop; not an iteration limit.
- Source staging and prompt restriction are not OS-enforced read isolation.
- No automatic public submission. Official score remains unknown until evaluated
  against privately held GT. Local artifact/validity checks are not that score.
- Account preflight: ordinary usage allowed, 59% weekly remaining. No reset used.

## Records

Runner: `evals/cadgenbench/scripts/run_native_autocad.py`.
Authoritative state and artifacts:
`evals/cadgenbench/runs/cadgenbench-111-codex-astra-ultra-autocad-20260916/`.
Model I/O: `attempts/a001/codex-events.jsonl`, `action-prompt.txt`, `codex-final.md`.
Native interface I/O: `attempts/a001/mcp-audit.jsonl`, plus referenced MCP jobs.
The transcript contains recorded public events, not unexposed internal reasoning.

Status: completed generation, ready for human review; not officially scored.
Started at 2026-09-15T19:01Z (2026-09-16 03:01 China time).
Native conversation: `01a0a671-d398-7562-bacd-4a2ef8563ac1`.
Supervisor PID at launch: `48224`. CLI version: `0.154.0-alpha.6.2`.
The installed executable directory changed to `12219cbfbcbddde7`; the prior
`bffc5354119c8421` directory no longer exists. No model substitution occurred.
Finished at 2026-09-15T19:36:26Z: 2113.689 seconds (35.23 minutes).
Model return code 0, no timeout, one continuous conversation, no supervisor
geometry hints or external repair prompts.

## Outcome

- `outputs/candidate.dwg`: one connected editable native AutoCAD Solid3d.
- `outputs/candidate.sat`: native ACISOUT export, SAT version 700.
- `outputs/renders/`: front and two isometric views derived from native STL export.
- Agent report and explicit assumptions: `outputs/model-report.md`.
- Agent self-checks: `outputs/verification.json`, 14 passed; these are not GT tests.
- Native check: valid ShapeManager solid; AUDIT found 0 errors, repaired 0.
- Final DWG reopened and SolidEdit Separate retained one connected solid.
- Native topology: 330 analytic faces, no export errors; volume 2480250.5266 mm3.
- Native extents: 316.7001 x 325.4021 x 80.0000 mm.
- SAT re-import: one valid solid, matching native volume and bounds.
- Supervisor independently loaded the final STL: watertight, consistent winding,
  one component, 18,938 triangles, positive volume 2482386.0442 mm3. Mesh/native
  volume difference reflects tessellation; this check does not prove task fidelity.
- DWG SHA256: `17cf33ed7921fa440f1e4e7a7195e6ccb1b19411dba343dc91e71929cfd1fbde`.
- SAT SHA256: `05f590c9d1b6e6e2675836e7103baa4ed6ae2b242f58206240d304cd812cf5de`.
- Final STL SHA256: `d095d361ecfd4fe4f4aeb7c38549323d91e55a1fffa608c26dc0d30178927c5d`.

Two side-port construction jobs failed: first after a self-intersecting profile
(exit 1), then with Core Console exit 3221226505. Astra read the actual logs,
revised its script, and successfully continued from the saved through-feature
DWG. It subsequently identified an ear-junction cusp in visual review and revised
the R25 transition. No human repair instruction was injected. All native jobs
reached terminal state, including the two failed jobs.

Remaining assumptions include passage width/endpoints, face groove depths,
several small blends, rib transitions, drilling depths, and bottom groove layout.
Some small corners remain sharper than the drawing. Do not describe this run as
an exact reconstruction, a strict benchmark pass, or a 100-point result.

## Archived Evidence

`recorded-execution/README.md` collects the prompt and public agent messages.
`attempts/a001/codex-events.jsonl` contains 156 raw CLI events;
`attempts/a001/mcp-audit.jsonl` contains 31 MCP calls. Fifteen native jobs are
snapshotted under `recorded-execution/autocad/`, including failed jobs and Lisp.
All 193 indexed file hashes and four frozen input/config hashes verified.
Archive manifest SHA256:
`8c3dd64da6c2a01283bf125e9d7542b6238d2f1b546904dfd026623763a6feac`.

CLI usage: 2783192 input tokens, 2583936 cached input tokens, 28350 output tokens,
and 11501 reasoning-output tokens as reported by the CLI. These are raw counters,
not an independently calculated bill. No reset credit or paid API switch occurred.

Eight runner/archive regression tests passed. Existing review bundles and their
scores were not modified. The new run is delivered as local DWG/SAT, PNGs, report,
and execution archive; no new entry was added to the GT-based review catalog.

## Recorder Maintenance

An inventory-only typo (`stat().st_size()` rather than `stat().st_size`) was found
by a regression test after the model had started. The launcher source was fixed;
the exact already-running source is preserved as `attempts/a001/runner-at-launch.py`.
It has no effect on the model prompt, tool behavior, CAD files, or model runtime.
The active Python process retains the original function, so its final artifact
inventory may fail after terminal execution state is saved. `archive_native_run.py`
can reconstruct the summary from that persisted terminal state and raw CLI events,
explicitly label the recorder recovery, and snapshot native jobs without any
model call, geometry edit, or CAD rerun. This recovery was performed successfully;
the original launcher stdout/stderr are preserved beside the raw CLI events,
and `result.json` explicitly records the recovery. No result is reported as scored.

## HTML Review And Submission Preparation (2026-09-16)

The later user request authorized public submission of the model and evaluation.
No upload has taken place yet: the official Submit handler requires a Hugging
Face OAuth profile. Authentication is pending user action, not a geometry failure.
The official README explicitly keeps `ground_truth.step` and jig volumes private;
published GT renders and submission ZIP downloads are not downloadable GT BReps.

- Review: `http://127.0.0.1:8770/?view=cadgenbench-astra-111`
- Records/comparison: `http://127.0.0.1:8770/astra.html?run=cadgenbench-astra-111`
- Frozen presentation data: `reports/generated/cadgenbench-astra-111-review`
- Adapted execution archive: `reports/generated/cadgenbench-astra-111-recorded-io`
- Submission package: `evals/cadgenbench/submissions/111-astra-ultra/submission.zip`

Same-fixture public report comparisons (not leaderboard averages): pzfreo Astra
High + build123d MCP reports CADScore 0.687, Volume IoU 0.664, Surface F1 0.380,
interface 0.770 and topology 0.850. Modelcorp Codex + Astra Low + CadQuery reports
0.662, 0.616, 0.446, 0.713 and 0.824 respectively. Values are rounded by the
reports, submissions are unvalidated, and harnesses / reasoning budgets differ.
Our accuracy metrics remain null. Source URLs and hashes are in comparison.json.

AutoCAD Core Console did not recognize IGESEXPORT; probe jobs are retained.
Installed SpaceClaim 2024 R2 translated the frozen SAT to STEP with no remodeling.
Local OpenCascade validation: one valid solid, 366 faces (native SAT: 330), volume
2480232.3640662287 mm3 vs native 2480250.5265947357 mm3; relative difference
7.322860457903424e-6, maximum bounds difference 1e-7 mm. Face splitting and
translation tolerance are disclosed; no claim of mathematically lossless export.
Original DWG/SAT hashes are unchanged. STEP SHA256:
`f203074051baf411e441c90e3db617b5aa22fd14ae60d61fcc465b7957f22cc7`.
The verification process persisted its JSON/package then exited 1 without a
traceback; the shutdown cause was not established. Independent stdlib checks
verified ZIP integrity, exact STEP hash, consent, and the two uploaded files.
No official validity result is inferred from the wrapper exit.

Submission ZIP: 81 official sample directories, only `111/output.step`, and
consent metadata. All other cases are explicitly missing, so its eventual
aggregate must NOT be used as a full benchmark score. No conversation logs,
local paths or credentials are included in the public ZIP.

Verification: 32 Python tests, 12 Node tests passed. Read-only browser checks
passed for desktop and mobile layouts, original/candidate images, comparison
values, 157 timeline records, 15 native jobs, nonblank canvas and orbit drag.
Screenshots and pixel-change evidence: `.local/reports/cadgenbench-111-html`.
The unscored state is neutral (not failed/zero); missing GT does not produce a
fake overlay or claim that no mismatch was detected. Historical review ledgers
and original experiment artifacts were not edited.
