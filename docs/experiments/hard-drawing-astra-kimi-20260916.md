# Contextual Drawing Challenge

## Request And Scope

The user requested harder boxed drawing questions and explicit edge-visibility
judgments, answered by Kimi. This is a new diagnostic batch, not a replacement
for boxed-r2 and not a matched-item comparison.

Plan: `evals/posttrain/boxed-hard-drawing-plan.json`.

- 20 proposed items on six original PDF sheets and one existing high-resolution
  valve drawing. No new download, image degradation, or external account setup.
- Eight edge visibility / geometric-versus-drafting-aid questions.
- Four additional contextual line-role questions.
- Four cross-view correspondence questions.
- Two section interpretation and two multi-dimension calculation questions.
- Previously used target rectangles are listed privately as exclusions.

Visibility refers to the represented edge in the relevant projection, not whether
ink is visible. Non-geometric center/dimension/extension/hatch lines must not be
classified as invisible edges. Sectioned and original uncut visibility are distinct.

## Existing Pipeline

Astra xhigh authors candidates; fresh Astra xhigh calls answer the actual rendered
boxed images without teacher answers, target-selection instructions or aliases.
Only accepted tasks reach native Kimi Code + kimi-k3, with the unchanged minimal
public prompt and observe/conclude/submit tools. One original-resolution drawing,
one rectangle, short Chinese query, no supplied operands or reasoning hints.

An optional `contextual-v1` audit rubric categorizes the minimum sufficient visual
evidence. Assignment-specific allowed categories stay private. Direct OCR or obvious
stroke recognition is `local_reading` and cannot pass this batch's difficulty gate.
This remains an LLM-based difficulty estimate, not expert confirmation. Disagreement,
ambiguity, insufficient difficulty and unmatched wording remain reviewable; thresholds
must not be relaxed after seeing learner results.

Dimension tasks additionally require at least three used named operands and two
arithmetic operations. The saved author plan and blind audit are hash-bound.
Existing plans without this profile retain their original validation behavior.

## Execution

Output: `.local/posttrain/real-drawings/boxed-hard-r1/`.
Controller: `evals/posttrain/run_drawing_diagnostic.py`.
Timeout: 600 seconds per Kimi item, unchanged from boxed-r2.
Completion publishes the frozen learner review on free port 8775. The existing
16-item results stay on 8774. Source rights remain private research only; labels
are model-proposed candidates, never verified ground truth.

`job.json` records stage/status and paths. Exact teacher and auditor requests,
image hashes, learner prompts, image receipts, public findings and submissions
are retained under the same output root. No hidden reasoning is inferred.

Validation before launch: `tests/test_drawing_qa.py`, 39 passed. Tests cover the
difficulty gate, private/public separation, immutable plan binding, actual boxed
image identity, alias handling, and used-operand checks.
