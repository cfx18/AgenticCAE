# Real Drawing QA Pilot

This is an extension of `cad_evoloop.posttrain`, not a new agent harness.
It evaluates Kimi drawing comprehension on real published drawings using
Astra xhigh model-proposed labels. It does not create CAD geometry or train models.

## Data Flow

1. `drawing_qa prepare`: render selected one-based PDF pages, acquire a small
   number of public article images, and preserve source hashes and rights notices.
2. `drawing_qa author`: call `gpt-6-astra` with `xhigh` through the existing
   `CodexCLIProvider`. Preserve exact prompts, input hashes, schema, output and usage.
3. `drawing_qa audit`: fresh Astra conversations receive only public questions
   and the same images, never the proposed answers or explanations.
4. `drawing_qa build`: validate regions, options, units and safe arithmetic;
   isolate ambiguous, nonvisual or disagreeing labels; seal ordinary task bundles.
5. Existing `run_kimi_smoke.py`: run native Kimi Code with observe/conclude/submit
   tools only. It cannot read private teacher labels or receive correctness feedback.
6. Existing review exporter and human-review ledger: show source images, crops,
   proposed answers, blind-audit evidence, Kimi answers, exact observations and findings.

The plan is `evals/posttrain/real-drawing-plan.json`: 20 questions on eight drawings,
with four each of line semantics, dimension attachment, dimension calculations and
cross-view correspondence, plus two each of sections and information sufficiency.
Numeric answers come from labeled dimensions, not assumed screenshot scale.

## Reproduction

Run inside the workspace with `PYTHONPATH=src`. Use new output directories for
each stage; old evidence is never overwritten. Source preparation requires Poppler
and the existing posttrain environment, not another CAD installation.

```powershell
$env:PYTHONPATH = "$PWD/src"
$Python = '.local/posttrain-env/Scripts/python.exe'
& $Python -m cad_evoloop.posttrain.drawing_qa prepare .local/posttrain/real-drawings/source-new --pdf '<user PDF path>' --pages 35 65 120 162 178 202 --catalog .local/posttrain/xifeng-discovery-r2/catalog.json --web-posts 1936 2679 2627
& $Python -m cad_evoloop.posttrain.drawing_qa author .local/posttrain/real-drawings/source-new evals/posttrain/real-drawing-plan.json .local/posttrain/real-drawings/teacher-new
& $Python -m cad_evoloop.posttrain.drawing_qa audit .local/posttrain/real-drawings/source-new .local/posttrain/real-drawings/teacher-new .local/posttrain/real-drawings/audit-new
& $Python -m cad_evoloop.posttrain.drawing_qa build .local/posttrain/real-drawings/source-new .local/posttrain/real-drawings/teacher-new .local/posttrain/real-drawings/audit-new .local/posttrain/real-drawings/tasks-new
& $Python evals/posttrain/run_kimi_smoke.py .local/posttrain/real-drawings/kimi-new --bundle .local/posttrain/real-drawings/tasks-new --timeout 600
& $Python -m cad_evoloop.posttrain.review export .local/posttrain/real-drawings/tasks-new reports/generated/real-drawing-review-new --learner-runs .local/posttrain/real-drawings/kimi-new
./evals/posttrain/start-review.ps1 -Bundle reports/generated/real-drawing-review-new -Port 8773
```

The Kimi runner reads the existing configured local Kimi environment. No API keys
or user configuration files are changed. Astra uses existing Codex authentication
and ephemeral CLI sessions; model artifacts are preserved in the workspace.

## Scoring And Review

The primary automatic metric is **agreement with a model-proposed reference**,
not expert correctness or CAD reconstruction accuracy. Fresh same-model agreement
can reproduce correlated errors. Human acceptance starts at zero.

- Numeric calculations are parsed with a bounded AST evaluator, not `eval`.
- Proposed numeric inputs still require visual/expert confirmation. Recomputing
  arithmetic does not prove the author read the drawing correctly.
- Author/auditor answer disagreements, low confidence, ambiguous targets and
  questions solvable without an image are quarantined before Kimi grading.
- Structurally valid quarantined tasks remain visible for human review, but the
  Kimi runner skips them rather than turning annotation errors into model failures.
- Kimi timeouts and missing submissions remain separate from answer disagreement.
- Exact full/cropped images, public viewing intent and stated findings are logged.
  These are public model records, not claimed access to hidden reasoning.
- Review decisions are immutable and hash-bound. They do not silently rewrite
  labels, alter a completed score, or approve material for training.

No original CAD GT is assumed. No downloaded executables or macros are run.
The PDF is user-supplied copyrighted material and the web images have their own
source notices; this local research inspection is not an open redistribution or
training license. Keep assets out of the public repository and obtain appropriate
rights before publishing or retaining a training dataset.
# Minimal Boxed Variant

`evals/posttrain/boxed-drawing-plan.json` defines 16 new items on eight of the
same source drawings. This is **not** a matched-item causal comparison with the
longer first batch. Protocol: `boxed-minimal-v1`.

- Public input: one full-resolution drawing with a thin red rectangle, a Chinese
  query of at most 35 characters, and `{"answer": ...}`. No choices, pre-made crops,
  semantic line hints, provided numeric operands, or prescribed reasoning steps.
- Astra xhigh proposes the target rectangle, answer, and private evidence. A fresh
  Astra xhigh call answers the actual rendered boxed image and minimal query, without
  seeing the author's answer or aliases. The learner receives that exact image hash.
- Ambiguous boxes, author/audit disagreement and low-confidence labels are quarantined.
  Same-model agreement remains a provisional label, not authoritative GT.
- Free-text scoring uses private synonyms frozen before Kimi runs. It does not use
  substring matching or a post-hoc LLM judge. An unlisted free-text answer is marked
  `answer_review_required` (ungraded), not automatically counted as a perception failure. Numeric scoring stays
  numeric and tolerance-bounded.
- `engineering-line-terms-v1` adds fixed equivalent engineering line names and
  compatible parenthetical stroke styles before bundle sealing. The resolved list is
  stored in the private verifier, and is also used for the blind agreement check.
  Arbitrary parenthesis removal and substring matching are not used.
- Native Kimi Code has the same public observation/submit tools, but only a short
  tool-use contract. Findings are optional; no explanation is requested. The exact
  prompt, image receipts and final submission are retained by the existing recorder.

The old `tasks-r1` / `kimi-r1` experiment is not modified or restarted.

One background job can execute all stages and export the existing review application:

```powershell
$env:PYTHONPATH = 'E:\AgenticCAE\src'
.local/posttrain-env/Scripts/python.exe evals/posttrain/run_drawing_diagnostic.py `
  .local/posttrain/real-drawings/boxed-r2 `
  --sources evals/data/posttrain/real-drawings/source-r2 `
  --plan evals/posttrain/boxed-drawing-plan.json --timeout 600 --review-port 8775
```

Use a fresh output directory. Optional `--authored PATH` reuses a complete, frozen
author stage with an identical plan; `--audited PATH` can reuse a complete blind audit
bound to those same questions. `job.json` records stage, status and failures;
`annotation-review` is available before Kimi finishes; `learner-review`, metrics and
the optional review server are created after the learner batch. All artifacts stay
inside this project. The source rights limitations below still apply.

## Read-Only Results Dashboard

`cad_evoloop.posttrain.results` combines sealed review bundles into a results
snapshot. `evals/posttrain/drawing-results.json` lists the three source batches
and six explicit post-hoc text equivalence assessments. Each assessment is bound
to the exact reference and submitted answer; mismatched evidence fails export.
They are assistant judgments, not human approval or validation of extra claims
inside a longer answer. The original automatic grades remain unchanged.

The exporter verifies the human-review ledgers and applies active, exact-attempt
`override_pass` / `override_fail` records separately. Conflicting active overrides
remain pending. On 2026-09-16 the user explicitly identified hard-15 as solid, not
a cavity. Review `989e3c8f7862479da53eae7f57ea01d7` records that statement as
assistant-transcribed user feedback, without inventing expert qualifications,
ratings, or approval of any other label.

Current snapshot after this feedback:

- Long prompt: 17 agreements / 18 tested; one timeout.
- Basic boxed: 12 / 16; two disagreements and two timeouts.
- Context-hard: 6 / 11; one human-confirmed error and four timeouts.
- Combined: 35 / 45 (77.8%) including timeouts; 35 / 38 (92.1%) among
  submitted answers. Eleven additional questions were quarantined before testing.
- Raw automatic agreement remains 29 / 45, with seven answers awaiting matching
  review. The adjusted snapshot resolves six as text-equivalent and hard-15 as wrong.

These are candidate-reference agreement rates, not expert-GT accuracy. Batches
are not matched-item comparisons. The dashboard exposes both denominators, raw
and adjusted outcomes, batch/type filters, original images, and exact task links.

```powershell
$env:PYTHONPATH = 'E:\AgenticCAE\src'
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.results `
  evals/posttrain/drawing-results.json `
  .local/reports/drawing-results-ui/report-new
```

Use a fresh output directory. Reports are snapshots; later human reviews require
a new export. No completed model run, bundle, or ledger is rewritten.

The local multi-bundle deployment uses
`.local/reports/drawing-results-ui/catalog.json`, with bundle IDs `long`, `boxed`,
and `hard`. Its presentation source copies the current posttrain app and existing
geometry viewer/vendor assets outside the sealed bundles. The catalog maps the
generated `results.html` as a supplemental page; presentation files are hashed
and snapshotted by the existing review catalog server. After an explicit restart:

```powershell
./evals/posttrain/start-review.ps1 `
  -Bundle evals/data/posttrain/real-drawings/reviews/boxed-hard-r1-learner-review `
  -Port 8775 -Catalog .local/reports/drawing-results-ui/catalog.json
```

Open `/results.html` for the dashboard or `/?batch=hard&task=hard-15` for the
bound question review. Scoped `/api/bundles/<id>/reviews` endpoints preserve each
bundle's original review ledger. Browser checks in
`tests/drawing-results-browser.cjs` cover denominators, both scoring modes,
six viewport widths, filters, JSON export, all batch deep links, image loading,
and the hard-15 record, while rejecting all writes during verification.

The review navigation and results table hide pre-test quarantined questions;
task totals and reviewed counts use only visible, eligible questions. Old links
to a quarantined task select the first eligible task in that batch. The sealed
evidence and exported audit JSON still retain the excluded records, and score
denominators are unchanged. The geometry review sidebar links to the results
dashboard on port 8775; the dashboard links back to geometry review on port 8770.

## User-Selected Unlabeled Probes

`cad_evoloop.posttrain.spot_check` packages a single source-hash-bound image,
normalized rectangle and short query. It reuses the boxed renderer, public-only
Kimi runner, image receipts, sealed bundles and existing review exporter. Unlike
the author/audit benchmark, an unlabeled probe has no invented teacher answer or
blind audit. Its `ungraded_answer` verifier only checks answer-submission format;
both correctness and score remain null. The results dashboard links these cases
separately, outside its accuracy denominators.

The OmniMech-4 probe is specified in
`evals/posttrain/omnimech4-line-probe.json`. Only its query and boxed original image
are public; the user selection description is private. The box covers a continuous
stroke in the upper-right outer circular drafting line, without labeling its role
in the prompt. The original drawing is not rescaled or redrawn.

```powershell
$env:PYTHONPATH = 'E:\AgenticCAE\src'
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.spot_check `
  evals/posttrain/omnimech4-line-probe.json .local/posttrain/spot-new/tasks-bundle
.local/posttrain-env/Scripts/python.exe evals/posttrain/run_kimi_smoke.py `
  .local/posttrain/spot-new/kimi --bundle .local/posttrain/spot-new/tasks-bundle --timeout 600
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.review export `
  .local/posttrain/spot-new/tasks-bundle .local/posttrain/spot-new/learner-review `
  --learner-runs .local/posttrain/spot-new/kimi
```

Use fresh directories. Add the exported bundle to the local review catalog and
its link to `diagnostics` in the results config, not to the scored `batches` list.

OmniMech-4 run `.local/posttrain/omnimech4-line-r2/kimi` completed on 2026-09-17
with status `timeout`: 600.38 seconds, ten observations, zero recorded conclusions,
and no submitted answer. This is not a correctness verdict. Build directory `r1`
was an incomplete packaging attempt, contained no model run, and was not published.
