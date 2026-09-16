# Geometry review sidebar, 2026-09-16

## Scope

The user identified mixed navigation and clipped filters in the upper-left
sidebar of `http://127.0.0.1:8770/?view=features`.

- Kept Harness and Experiment selection at the top, with wrapping selected names.
- Moved independent Astra/Kimi exports into a harness-grouped archive dialog.
- Added an exact-experiment record link only where an export exists.
- Collapsed optional case filters and audit statistics by default.
- Added active-filter count/reset; desktop filters use full-width controls.
- On narrow screens experiment controls share a row and the case list scrolls
  independently. Expanded filters are no longer clipped by a fixed-height sidebar.
- Preserved geometry comparison, scores, experiment IDs, draft scoping, and review
  submission bindings. No model run or benchmark was started or modified.

## Verification

- JavaScript navigation, archive, filter, Astra records, and benchmark-metric
  tests: 15 passed.
- Python geometry review/export/catalog tests: 23 passed.
- Playwright before deployment and against the restarted live server: passed at
  1920, 1600, 1280, 1040, 800, 675, 390, and 360 pixels.
- Checked long experiment names, filters/reset, archive keyboard dismissal,
  record URLs, Harness/Experiment switches, and synchronized 3D orbit with canvas
  pixel checks. No page exceptions or failed HTTP responses.
- Review ledgers and frozen review-data files were hash-checked before/after the
  browser runs; they remained unchanged. No human review was submitted.

Screenshots and machine-readable results:
`.local/reports/geometry-sidebar-20260916/{source,live}/`.

Only the verified geometry review listener on 8770 was restarted. Catalog mode
created a new presentation snapshot; old evidence bundles were not rewritten.
