# Drawing Review UI Revision

## Scope

The user found the task review screen difficult to read. This revision changes
presentation only; it does not restart model jobs, change questions or labels,
modify input images, or overwrite historical evidence and reviews.

- Compact Chinese task list with previous/next navigation and category filtering.
- Default page: question, large drawing viewport, and adjacent reference/Kimi answers.
- Review-only focus on the marked region, full-sheet fit, wheel/button zoom, pan,
  touch support and original image link. Learners still receive the same original input.
- The human review form is a modal drawer, retaining per-task unsaved drafts.
- JSON contracts and provenance are collapsed under a separate details tab.
- Image receipts are grouped as intent, actual returned image, and recorded findings.
  Missing findings are explicitly identified, not synthesized.
- Model-authored labels remain provisional. Preview snapshots are explicitly marked
  as not containing live results; no absent result is reported as a model failure.
- Existing synchronized 3D comparisons remain available for tasks with geometry.

## Deployment And Integrity

The existing `ReviewCatalog` presentation snapshot mechanism serves the new UI over
the unchanged boxed-r2 annotation review bundle and its original review ledger.
New human reviews carry both the original evidence binding and the presentation hash.
No review was migrated or recreated as if a human had submitted it.

Current address: `http://127.0.0.1:8773/`.
Presentation configuration: `.local/reports/posttrain-ui-v2/catalog.json`.
Frozen presentation source: `.local/reports/posttrain-ui-v2/presentation-r2/app`.
Original evidence: `.local/posttrain/real-drawings/boxed-r2/annotation-review`.

The SHA-256 of the original `review-data.json` was unchanged before/after deployment:
`937a6842cceb1305e437527cd8122322dbe740b981c4cb0565f9162d28e068f2`.
There were no human-review ledger records before or after the read-only UI tests.
Only the verified review servers on ports 8773, 8778 and 8779 were restarted/stopped;
model runner processes and the other review services were not touched.

## Verification

- All 16 real boxed questions, target visibility, pan/zoom, full/focus switching,
  answer display, provenance links, draft isolation and modal controls passed.
- Six viewport widths: 1920, 1600, 1280, 800, 390 and 360 pixels; no horizontal overflow
  or browser errors. Desktop and mobile screenshots were visually inspected.
- Review submission was intercepted in the browser test, not written to the real
  ledger; assertions checked task, attempt, bundle and presentation bindings.
- A clearly synthetic browser-only trace fixture checked grouped image/findings
  rendering and HTML escaping. It was never exported as model evidence.
- The 20-task legacy 3D review regression passed, including nonblank canvas pixels,
  synchronized orbit changes and mobile rendering.
- Python checks: 99 passed, 2 skipped (`trimesh` unavailable in the isolated env).
  The independent browser geometry checks above did run and pass.
- Repository-wide whitespace check reports a pre-existing unrelated trailing space
  in `docs/BOOLEAN_FACE_LINEAGE.md`; that file was not changed for this UI work.

Artifacts: `.local/reports/posttrain-ui-v2/live-screenshots` and the existing
`.local/reports/posttrain-ui` 3D regression screenshots. Lucide 0.468.0 is vendored
with its license under the shared review vendor directory; no runtime CDN is needed.
