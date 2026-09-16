# Minimal Boxed Drawing Questions

## Motivation And Protocol

The user observed that the first real-drawing batch supplies too much textual
localization and plausible answer options. This follow-up removes those aids.

- Teacher and blind reviewer: `gpt-6-astra`, `xhigh`, separate ephemeral Codex calls.
- Learner: native Kimi Code + configured `kimi-k3`, public-only MCP tools.
- New plan: `evals/posttrain/boxed-drawing-plan.json`, 16 items on eight real drawings.
- Categories: six line-role, four direct dimension, four dimension-chain, two
  sectional solid/void items. Counts are planned, not claimed successful results.
- Input: one full drawing marked with one red rectangular outline and a <=35-character
  query, without numeric hints, choices, supplied crops or solution steps.
- Output: `{"answer": ...}`; no explanation required. Observation crops remain
  available, with exact image receipts. The minimal system prompt is also frozen.
- Same per-item timeout as the prior batch: 600 seconds; one final submission;
  no label/reward feedback during the episode. Timeouts are ungraded, not wrong answers.
- Frozen private aliases tolerate short synonymous line names. There is no dynamic
  semantic judge or automatic repair of labels after seeing Kimi's answer. Unmatched
  free text is `answer_review_required`, not an automatically scored semantic failure.

These are new targets, and the system prompt also changes. Comparing aggregate scores
with the first batch is descriptive, **not** a controlled same-item prompt ablation.
Image source and drawing content are unchanged except for the ROI rectangle. Astra
must independently validate the actual annotated pixels with the terse question.
Disagreements and ambiguous boxes are retained for review but excluded from Kimi testing.

## Artifacts

- Sources: `.local/posttrain/real-drawings/source-r2` (unchanged).
- Author stage: `.local/posttrain/real-drawings/boxed-teacher-r1`.
- Old verbose tasks and running learner: `tasks-r1` and `kimi-r1` (untouched).
- Active follow-up pipeline: `.local/posttrain/real-drawings/boxed-r2` (stage/status in `job.json`).
- Runner: `evals/posttrain/run_drawing_diagnostic.py`; reuses existing bundle,
  environment, verifier, learner recorder and review app. No separate data framework.

Both author batches completed: 16 questions, zero structural/arithmetic validation
errors. The real rendered boxes were visually inspected; both contact sheets are in
`.local/posttrain/real-drawings/boxed-inspection-r1`. This is not human expert acceptance.
The independent audit and downstream learner/export chain were started as a hidden
background job on 2026-09-16 at 19:10 China time. Five audit responses used equivalent
terms not listed by the author (for example, hidden line vs fine hidden line, or a
line name followed by its stroke style in parentheses). The r1 exact alias gate
incorrectly quarantined those items. Its learner job was stopped and marked superseded;
all r1 records remain, and its incomplete learner run is not used for this experiment.

Revision r2 freezes `engineering-line-terms-v1` before its learner run. This is a fixed
terminology expansion, not substring matching, arbitrary parenthesis removal, an LLM
judge, or a rule derived from Kimi answers. Only known equivalent names and compatible
stroke descriptions are expanded. Unlisted free-text learner responses still require
human review. The actual accepted strings are included in each sealed private verifier.
The original author and blind-audit calls are reused unchanged, including the exact
audited image hashes. Under this policy, all 16 items agree and pass the confidence/
answerability gates; this is still same-model agreement, not verified GT.

R2 began at 19:18 China time. `job.json` is the live status source. The annotation-only
review is served at `http://127.0.0.1:8773/`; it is a fixed pre-learner snapshot, so
its "Not run" label is not a live batch status. The final learner review is configured
to start on port 8774 after completion. Both verbose `kimi-r1` and boxed `boxed-r2`
run in the background. Shared-machine/API concurrency is not a controlled latency benchmark.

Verification: 115 Python tests passed. Browser checks passed for all 16 boxed inputs
(red rectangle pixels, no choices, short questions), reference labels, downloads,
draft isolation, no page errors, desktop/mobile overflow. No human reviews were saved
by these tests. Learner-receipt browser acceptance remains pending batch completion.
No new Kimi score is claimed here. Labels remain `model_proposed_not_gt`; human acceptance is pending.
The book and public web drawing rights have not been cleared for redistribution.
