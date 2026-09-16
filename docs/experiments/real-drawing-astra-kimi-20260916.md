# Real Drawings: Astra Authoring and Kimi QA

Date: 2026-09-16. Scope: private noncommercial diagnostic, not training.

## Frozen Inputs and Teacher Records

- User PDF: `source-r2/source.pdf`, 260 pages; selected PDF pages 35, 65, 120,
  162, 178 and 202 (one-based file pages, not printed page numbers).
- Selected web drawings: Xifeng posts 1936 (reducer assembly) and 2679
  (multi-view support part). Public image requests use their actual referring
  article. No VIP content, account login or CAD archive extraction was used.
- Root: `.local/posttrain/real-drawings/`.
- `source-r2/sources.json`: source URLs, PDF identity, image hashes, dimensions
  and rights notices. It includes unused preview candidates; the plan specifies
  the eight images actually passed to the teacher.
- `source-r1/`: exploratory source inspection, not the accepted input set.
  Older competition article previews included CAD renders and low-quality
  screenshots; these were not selected for the final question plan.
- `teacher-r1/`: two Astra xhigh authoring calls, exact inputs and JSON output.
- `audit-r2/`: two fresh Astra xhigh blind-answer calls. They receive question
  wording and original images, but not teacher answers or explanations.
- `audit-r1/`: failed before model invocation because Windows tried reading
  UTF-8 Chinese metadata as GBK. No model charge/result is attributed to that
  failed stage. The affected file reads now explicitly use UTF-8.

## Acceptance

- 20 proposed questions; structural, crop-coordinate and arithmetic checks pass.
- 20/20 author/blind-answer agreements. This is same-model agreement, NOT expert
  correctness and NOT independent CAD ground truth.
- 2 questions quarantined as answerable from wording without the image:
  `drawing-05` supplies both numeric operands; `drawing-17` gives the identifying
  line style, letter and paired-position relationship.
- 18 tasks eligible for the Kimi diagnostic; all 20 remain human-reviewable.
- Eligible families: 3 line-role, 4 dimension-attachment, 3 dimension-chain,
  4 cross-view, 2 section-interpretation and 2 information-sufficiency tasks.
- Bundle: `tasks-r1/`. Each task keeps public inputs separate from private
  annotation, verifier and blind-audit evidence, with immutable manifest hashes.
- Human acceptance: zero at experiment launch. No automated human review was saved.

## Learner Protocol

`kimi-r1/` uses the existing native Kimi Code runner and existing Kimi K3
configuration, one fresh restricted-tool session per eligible question. Available
tools are observe, conclude and submit. There is no shell/file-read/CAD tool and
no access to the private proposed answer or correctness feedback. This is a
capability restriction, not an OS sandbox claim.

The wall-clock backstop is 600 seconds per task. Timeout/missing submission is
reported separately from disagreement. No repair retry or best-of selection is
allowed. Scores mean agreement with the model-proposed reference, pending review.
Every observation records intended inspection, exact returned image/hash/crop
and optional subsequent stated findings. Final answers are read from the submitted
snapshot, not a mutable working file.

## Verification

- 103 focused Python tests passed after the UTF-8 correction.
- Existing CAD review mode passed desktop/mobile browser regression including
  nonblank geometry and synchronized orbit.
- The 20-task annotation-only review passed image loading, no page overflow,
  reference-label mode, download links and per-task draft isolation checks.
- Final learner results and learner-image-receipt browser checks are pending
  completion of `kimi-r1/`; do not cite this document as a completed accuracy run
  until the results section is updated.

Integration and reproduction: `docs/REAL_DRAWING_QA.md`.
