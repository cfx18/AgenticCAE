# Native Codex Ultra: OmniMech 2 and 10

Requested on 2026-09-14: repeat OmniMech 2 with Astra Ultra, and reconstruct
OmniMech 10 independently with Sol Ultra and Astra Ultra.

## Registered Runs

- `direct-codex-astra-ultra-omnimech2-https-20260914`: `omnimech:2`, `gpt-6-astra`, `ultra`.
- `direct-codex-sol-ultra-omnimech10-https-20260914`: `omnimech:10`, `gpt-5.6-sol`, `ultra`.
- `direct-codex-astra-ultra-omnimech10-https-20260914`: `omnimech:10`, `gpt-6-astra`, `ultra`.

The existing OmniMech 2 Sol control is
`direct-codex-sol-ultra-omnimech2-https-20260914`. Its outputs are not provided to
any new modeling conversation.

## Fixed Conditions

- Native Codex CLI `0.154.0-alpha.6.2`, executable in the installed `bffc5354119c8421` bundle.
- The same signed-in Codex account, HTTPS transport, no separate paid API key.
- One fresh continuous conversation per run, a 3,600-second safety timeout,
  no EvoCAD outer loop, no forced IR, no in-run ground-truth scoring.
- The unchanged `direct_codex_trial.py` prompt and audited AutoCAD MCP interface.
- Sequential runs using isolated Core Console jobs, not the desktop CAD session.
- Source-only input staging; this is a prompt restriction, not an OS read-isolation claim.
- Post-run geometry-v2 scoring: 20,000 surface samples and voxel resolution 64.
- Separate campaign, task, artifact, public trajectory, audit and hash-chained ledger paths.

Input-image SHA-256:

- OmniMech 2: `fef27d4171b22c08156d694224383ccae3dae7e5fc998ee880f7613c7692bef6`.
- OmniMech 10: `65060dcbfb0960e50c984d9c9f5bd87f1d8dbecdc12bf0e7189546aab7565124`.

Account preflight reported 92% weekly usage. Ordinary usage remained allowed.
No reset credit was redeemed or authorized. Provider/quota failures must be
recorded as infrastructure failures, not interpreted as geometry capability scores.

## Status

All three runs are complete, with normal agent stops and no safety timeouts.
The authoritative per-run execution state is
`evals/geometry-benchmarks/batch/<campaign>/trial-config.json`.

Results are exported as new frozen review bundles and registered in the Codex
harness catalog, without overwriting any earlier run or human review. Review URLs:

- Astra / OmniMech 2: `http://127.0.0.1:8770/?view=direct-astra-2`.
- Sol / OmniMech 10: `http://127.0.0.1:8770/?view=direct-sol-10`.
- Astra / OmniMech 10: `http://127.0.0.1:8770/?view=direct-astra-10`.

## Astra / OmniMech 2

Later human-requested [mirror diagnosis](astra-omnimech2-mirror.md) reached 100
after reflecting the whole solid. That post-hoc result is separate from the
unchanged original autonomous score below.

- Score: 91.69; strict pass: false. IoU: 0.890819; normalized Chamfer: 0.007152.
- Bounding-box error: 0; volume error: 0.0483%; surface-area error: 0.0550%.
- Watertight candidate; one native editable Solid3d; final native topology export has no errors.
- 929.209 seconds; normal agent stop, not timeout. The native agent interpreted the
  drawing, built the body, cut the bores, rendered its own inspection views, and
  recovered a final-save crash by returning to an intact intermediate drawing.
- Root public task: `01a0a035-ceec-7e23-b3e3-3ab1075af4f1`.
- One native auxiliary task: `interpret_geometry`.
- Root CLI usage: 1,077,613 input tokens (1,012,992 cached), 13,784 output tokens;
  not claimed to be the verified total across every auxiliary task.
- Candidate SHA: `31bf9f7c5de9dfec19486bab66f2f4f34b3ce960d734b542b1b8942f1ac59688`.
- Review bundle SHA: `47e79b8535eacc2a57c328fae3f73e3b50ce6383c247085e0d2a6bdf15bdb8f4`.
- Ledger verified after preserving 20 additional work products: 61 files, 48 events.
  Public root/helper exports omit reasoning items and live beside the review bundle
  under the campaign's `-public-traces` directory.

The previous native Sol Ultra control scored 63.34 (IoU 0.878517, Chamfer 0.009053,
volume error 5.1968%). Astra improves these observed metrics, but the 28.35-point
score increase includes recovering the volume component, not a 28-point IoU gain.
This remains one trial per model on one sample, not a broad model ranking.

## Sol / OmniMech 10

- Score: 100.0; strict pass: true. IoU: 0.999824; normalized Chamfer: 0.004384.
- Bounding-box error: 0; volume error: 0.0459%; surface-area error: 0.0875%.
- 981.899 seconds; normal agent stop, not timeout. The agent corrected its initial
  interpretation of the stepped T-slot and underside feet using enlarged input
  views, rebuilt the solid, rendered it, and reopened the final DWG for topology checks.
- One native model-space solid, 80 x 30 x 65 mm bounds, four diameter-3.4 through
  holes, one nominal diameter-5 blind hole. Final topology export has zero errors.
- Root public task: `01a0a045-306d-7fe3-9267-9ada0115962a`.
- Three native auxiliary tasks: `drawing_interpretation`, `cad_strategy`, `dimension_audit`.
- Root CLI usage: 1,699,207 input tokens (1,619,584 cached), 19,740 output tokens;
  not claimed to be the verified total across every auxiliary task.
- Candidate SHA: `4dfb2ca5c41c351460235c81af4d6a32be99d4c1517206f9eb506157aa7bf921`.
- Review bundle SHA: `9cd0fd2a67068151a974c6b27e390d83d389450d808ef2dcfa06fd83bd628247`.
- Ledger verified after 18 supplementary work products: 59 files, 46 events.

The historical EvoCAD V2 / Sol medium result for this sample was 76.14. That is
not a harness-only ablation: reasoning effort, feedback access and other execution
conditions differ. The native Sol/Astra pair in this experiment uses matched input,
effort label, prompt, tools, scoring protocol and time cap.

## Astra / OmniMech 10

- Score: 100.0; strict pass: true. IoU: 0.999824; normalized Chamfer: 0.004399.
- Bounding-box error: 0; volume error: 0.0459%; surface-area error: 0.0875%.
- 705.037 seconds; normal agent stop, not timeout. The agent independently resolved
  the same feature dimensions, constructed the body and cuts in successive Core
  Console jobs, checked native faces and mesh connectivity, and saved one native solid.
- Root public task: `01a0a055-5173-7073-8d9c-8bfc730e7446`.
- One native auxiliary task: `drawing_review`.
- Root CLI usage: 738,796 input tokens (697,856 cached), 10,548 output tokens;
  not claimed to be the verified total across every auxiliary task.
- Candidate SHA: `7f5dcdf16257e2fd631b33486713024277fc5b9f389b98d1211bfcf32694d6fb`.
- Review bundle SHA: `d85851df212a85a7f16273c13f67511cd6b8b84d34b31618903559213e70a943`.
- Ledger verified after 12 supplementary work products: 53 files, 36 events.
  The agent's stage02 topology is archived as intermediate evidence, not relabeled
  as a final-candidate topology export.

Both models strictly pass OmniMech 10. Astra took about 11.8 minutes versus Sol's
16.4 minutes in these single trials. Neither received the other model's output or
held-out scores during reconstruction. Scores of 100 indicate passing this frozen
geometric protocol, not a guarantee of manufacturing correctness or full thread detail.

## Publication Checks

The catalog now has nine frozen experiment views, including four native Codex
results. Presentation SHA:
`53c55dd72aa59bbc3111588d8b5834fca978a322e49fcdc0745b05a96159f4f5`.
All bundle/review integrity checks passed; the three original reviews are unchanged.
The live 8770 and 8765 services use the expanded catalog. Browser checks verified
each new score/model/sample binding, complete input images, nonblank geometry and
synchronized dragging. Browser error/warning log was empty. No real test reviews
were submitted. Regression checks: 30 Python tests and 6 Node navigation tests pass.

The mismatch panel still shows local discrepancies in the strictly passing
OmniMech 10 outputs, including the threaded-hole region. The metric thresholds and
capped component scores allow local residuals; retain these observations for human
review instead of claiming zero geometric error.
