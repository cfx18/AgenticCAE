# Astra Execution Records

Local entry point: `http://127.0.0.1:8770/astra.html` (also served on port 8765).
The Geometry Review sidebar links to this page in a separate tab so existing
human-review drafts are not replaced.

## Inventory

The completed local result inventory on 2026-09-15 contains four autonomous Astra
runs and one human-requested diagnostic, across three samples:

- `direct-astra-2`: native Codex, OmniMech 2, score 91.69, strict fail;
  65 CLI events, 15 MCP calls, 5 native jobs, 169 export files.
- `direct-astra-4`: native Codex, OmniMech 4, score 100, strict pass;
  65 CLI events, 13 MCP calls, 5 native jobs, 181 export files.
- `direct-astra-10`: native Codex, OmniMech 10, score 100, strict pass;
  53 CLI events, 11 MCP calls, 4 native jobs, 135 export files.
- `evocad-astra-2`: EvoCAD, OmniMech 2, score 100, first-candidate strict pass;
  109 CLI events, 28 MCP calls, 13 native jobs, 460 export files.
- `mirror-astra-2`: human-requested mirror of the native Codex candidate, score
  100. Zero new model calls, one native job, 55 export files. Not an autonomous
  pass and not a replacement for the original 91.69 result.

Total: 292 CLI events, 67 audited MCP calls, 28 native jobs (27 agent jobs and one
human diagnostic), and 1,000 manifest-indexed export files including the five
manifests. These are repeated artifact views/copies, not 1,000 unique CAD states.
All files and five ZIP hashes were verified. No model/CAD rerun was needed.

The EvoCAD action interruption and recovery are included. Its displayed 705-second
attempt time excludes initial interrupted work; total initial-launch-to-completion
was 1594.503 seconds. Native OmniMech 4's post-evaluation topology-export incident
and restored scored candidate are preserved in its raw campaign evidence.

## Viewing

- Overview: original input, candidate and overlay, metric results and experimental
  caveats. Geometry review opens the existing interactive synchronized viewers.
- Model I/O: saved prompts and CLI-emitted events in phase/line order, searchable
  by text and filterable into messages, inputs, tools, and evaluator evidence.
- AutoCAD jobs: ordered job submissions, actual submitted Lisp, backend wrappers,
  native logs and topology snapshots. Human diagnostic jobs are labeled separately.
- All files: manifest-indexed artifacts, text/image preview and original downloads.
  Download ZIP preserves the full original export.

The canonical timeline does not double-count copied reflection compatibility
streams. Original raw streams remain in each package, including unfinished events.
Older native job files not present in the original ledger were copied at export
time and labeled `postrun_snapshot_files`, not presented as contemporaneous model
observations. Files with known changes/side effects remain distinct evidence.

## Implementation

- UI: `apps/geometry-review/astra.html`, `astra.js`, `astra.css`.
- Registration: `recorded_io` on each relevant `apps/geometry-review/catalog.json`
  entry, bound to both export-manifest and ZIP SHA-256.
- Exporter: `evals/geometry-benchmarks/scripts/export_geometry_trajectory.py`.
  Selects the campaign-owned run when a diagnostic report includes its historical
  parent as a comparison; it does not relabel the parent's result as a new run.
- Backend: `RecordedIOArchive` in `review_catalog.py`; read-only routes at
  `/recorded-io/<catalog-id>/<manifest-listed-path>` and `archive.zip`.
- Only manifest-listed files are served. Paths and file hashes are verified;
  unlisted/escaping paths fail closed and changed artifacts return a conflict.
  Download responses use attachment disposition, octet-stream and `nosniff`;
  textual artifacts are rendered with escaping, never executed as page code.
- The updated UI receives its own presentation hash/snapshot. Historical evidence
  bundles, scores and review ledgers are not overwritten.

## Completeness Limits

This is the complete locally recorded experiment evidence, not an HTTP protocol
capture or private model reasoning trace. Model-service internal prompts, private
reasoning, image tokenization and already-truncated outputs cannot be recovered.
MCP timestamps are retained; CLI events without absolute timestamps retain their
original stream order without fabricated cross-stream timing. Native logs being
available does not mean the Agent read every line; the command/MCP returns record
the observations actually delivered by the local runner.

## Verification

- 34 Python tests passed for exporting, archive path/hash checks, download MIME
  protection, existing review behavior, HTTPS trial setup and topology isolation.
- 9 JavaScript tests passed for escaping, provenance/filtering and existing review
  navigation/draft preservation.
- Browser checks passed for all five experiment bindings, a real failed MCP-call
  search, native Lisp/log switching, raw input-image preview and desktop/mobile
  layout. The mobile title/score collision was corrected before delivery.
- All five ZIPs were downloaded into memory through the HTTP endpoint and matched
  their registered hashes. Both 8765 and 8770 health endpoints were healthy.
- Original geometry review retained the Astra archive link and all three viewers
  reported `3D`, with no browser console errors/warnings. No human review was added.
- Served presentation SHA:
  `561c33885c17575f2c6e75bd90230c50dd35ec508b8438ef454fedc7758bd222`.
