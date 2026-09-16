# Kimi Visual Trace

Run from the workspace root:

```powershell
.\evals\geometry-benchmarks\scripts\export-kimi-vision.ps1 -Sample 2 -Harness evocad
```

Choose sample 2, 4, or 10 and harness `evocad` or `direct`. The case must already
have an action event log. The command extracts a new immutable snapshot, updates
the review catalog, and refreshes only the expected local catalog server.
The page is `http://127.0.0.1:8770/kimi-vision.html`. No model API is called.

Export all three original native Kimi Code runs:

```powershell
.\evals\geometry-benchmarks\scripts\export-kimi-vision.ps1 -Harness direct -All
```

Each case has a stable page: `kimi-vision-direct-2.html`,
`kimi-vision-direct-4.html`, and `kimi-vision-direct-10.html`. EvoCAD runs use
`kimi-vision-evocad-N.html`, so exports no longer overwrite another harness's
only entry point. The default page selects native Kimi case 2 when available.
Pages also include the original task prompt, all recorded non-image tool
arguments and text returns, and public assistant messages. The harness label
comes from the experiment records, not a hardcoded EvoCAD label.

For extraction only, without changing the page or restarting its server:

```powershell
.local\geometry-env\Scripts\python.exe evals/geometry-benchmarks/scripts/export_kimi_visual_trace.py --job <job-directory> --output <new-workspace-output-directory>
```

Outputs: standalone `index.html`, structured `trace.json`, exact tool-returned
images, and `manifest.json` with SHA-256 bindings. An active log is read once at
a bounded length; its incomplete final line is excluded. Later exports preserve
earlier snapshots and do not change the running experiment or its prompts.

Each `ReadMediaFile` call contains:

- `wanted`: requested path/region and adjacent public explanation. The request
  rectangle is known; semantic intent without a public statement is not known.
- `images`: the original embedded image payloads from the tool return, not
  reconstructed crops of the current file. Both byte and RGBA-pixel hashes are
  recorded, along with dimensions and delivery metadata.
- `found`: nearby public follow-up statements and conservative observation
  candidates. Next-action announcements are not discoveries. Statements after
  another non-image tool call are not attributed to the image. Parallel crops
  share public context and cannot always be individually attributed.
- `previous_operations`: neighboring public command requests, for checking
  crop, resize, grid overlay, line extraction, and other preprocessing.

This is deterministic evidence extraction, not an LLM interpretation layer.
Private reasoning is never exported. Public observation candidates are model
claims, not independently verified geometry facts. Tool delivery does not prove
model attention or comprehension. Missing observations are labeled as missing.

## Initial Finding

The 2026-09-16 13:01 local snapshot of EvoCAD/Kimi OmniMech 2 contains 73 media
calls: one whole drawing, 49 source crops, and 23 derived images. All returned
images; 72 distinct pixel payloads were observed. Call 50 repeats call 27 exactly.
No AutoCAD call appears in that prefix. Public actions progress from crop-based
reading to pixel calibration, line/circle detection, and grid-annotated crops.
This supports an observation-to-execution stall, not a repeated failed-image
delivery diagnosis. It does not establish the model's hidden internal cause.
