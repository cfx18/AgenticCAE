# Kimi Failure Pattern Audit

Date: 2026-09-16. Read-only diagnosis of existing runs; no model or CAD rerun.
This supplements the [failure inventory](../FAILURE_PATTERNS_20260916.md).
Evidence is public assistant text, tool input/output, verifier results, and runner
code. Recorded reflections are claims to check, not authoritative causal labels.

## Scope And Outcome

- Native Kimi Code + K3, OmniMech 2: score 88.96, IoU 0.887791, agent stop.
- Native Kimi Code + K3, OmniMech 4: score 53.03, IoU 0.793316, agent stop.
- Native Kimi Code + K3, OmniMech 10: score 10.78, IoU 0.163514, time budget.
- EvoCAD + Kimi, OmniMech 2: score 0, four attempt records, no DWG, no mesh,
  zero verifier coverage. This is missing output, not measured zero similarity.
- EvoCAD + Kimi, OmniMech 4/10: not started. They are not failed model cases.

These are four runs of three parts, not four independent problems or a model
ranking. Native runs had no in-run GT feedback. EvoCAD's zero-output run never
reached geometric comparison, so it did not test response to localized mismatch.

## 1. Observation Without An Executable Checkpoint

Confirmed: EvoCAD a001 contains 75 image calls (74 distinct returned pixel
arrays), 67 Bash calls, five Write calls, and zero AutoCAD calls. All image calls
have image returns. The exported prefix hash matches the final a001 transport
event hash: `93d1ea8417b51b156467f30f36645337e9369a9644d5ed6b5f2087dfbb35c9e5`.
The first action ran until the approximately 4860-second deadline without a DWG.

Its public trajectory proceeds through crops, segment extraction, Hough circles,
color masks, coordinate grids and ASCII views. Late messages still request hole
and section measurements. Native OmniMech 10 has all 25 image calls before its
first CAD start (event line 101); it ultimately produces only a partial base.

Pattern: observation and custom image-processing expand without an early
testable CAD artifact. This does not mean it repeatedly received the same image:
only one EvoCAD call repeated exact pixels; native 2/4/10 have zero such repeats.
Nor do image counts measure attention, correctness, or time spent per image.

Intervention to test: track unresolved feature questions and explicit evidence
updates; expose elapsed time; request an early recoverable primary solid while
retaining uncertain details for later refinement. Do not replace this with an
arbitrary maximum image count or a rule that approximate geometry is sufficient.

## 2. Recovery Action Starved By The Harness

Confirmed code defect: each action reserves 540 seconds for a decision plus two
possible decision retries. `remaining_attempt_timeout` clamps even a negative
action budget to one second.

The first post-action feedback reports 538.6 seconds remaining. After its
decision, all subsequent actions therefore receive a one-second process timeout.
The a002, a003 and a004 event files each contain only the same CLI version event;
there are no recorded assistant actions, image reads, or CAD calls in them.

The actual budget helper was evaluated locally with the recorded remaining
values, without launching any model:

```text
decision reserve = 540 seconds
remaining 538.6 -> action timeout 1
remaining 465.4 -> action timeout 1
remaining 410.9 -> action timeout 1
remaining 347.6 -> action timeout 1
```

The 54.405 / 63.112 / 47.157 second attempt durations include decision work and
overhead; they are not the three action timeouts. Hence four attempt records do
not imply four meaningful modeling opportunities.

Ownership: harness. First-action over-observation is separate from the later
starvation. A corrected budget may enable recovery but does not guarantee it.

Intervention to test: admit a new action only with a meaningful execution budget;
bound the decision reserve by remaining resources; make retry reservation
adaptive; include low-budget regression tests. Preserve original run results.

## 3. Reflection Explains A Failure It Cannot Observe

Confirmed: a002/a003 reflection attributes the repeated timeouts to every turn
being consumed by drawing analysis. Their action streams contain only startup
metadata. Those causal statements are unsupported for these turns.

The feedback packet exposes total remaining seconds, a timeout flag, return
code, MCP calls, and stderr. It omits allocated action seconds, actual action
elapsed time, first-response status and native non-MCP activity counts. Kimi is
told hundreds of seconds remain while the launcher grants its action one second.
The transport sidecar also lacks the actual allocated timeout.

Pattern: incomplete execution feedback invites a plausible narrative that
repeats the preceding turn's explanation. Kimi does identify harness ownership
and propose infrastructure changes, but not the specific allocation defect.

Intervention to test: supply action-budget and startup/progress telemetry;
separate observed facts, hypotheses, and discriminating next checks in diagnosis.
Do not train on the existing reflection text as if it were verified root cause.

## 4. Self-Consistency Mistaken For Reference Correctness

Confirmed: native OmniMech 2 reports that projections match exactly. Its final
verifier has zero bounding-box error and only 0.2032% volume error, but IoU is
0.887791 and normalized Chamfer is 0.007783. Global measurements can agree while
spatial occupancy differs. The metrics alone do not identify the responsible hole,
channel, alignment or handedness; feature-level adjudication is still required.

Native OmniMech 4 checks a roughly 81124 mm^3 CAD volume against its own roughly
81100 mm^3 analytic estimate and declares views checked. Against GT, volume error
is 6.5328%, bbox error is 0.5723%, and IoU is 0.793316. A formula derived from the
same interpreted dimensions checks implementation consistency, not whether those
dimensions and feature semantics were read correctly.

Pattern: successful CAD execution and agreement with an internally derived plan
support stronger completion claims than the evidence warrants. The model does
perform real checks; calling this "no verification" would also be inaccurate.

Intervention to test: independent source-linked feature checks, registered
projection/section comparisons with visible discrepancy evidence, and explicit
uncertainty in the final result. A 2D proxy must not silently replace 3D metrics.
These native runs never saw the low GT scores, so "ignored verifier feedback"
is not a supported label.

## 5. Precise Numbers From Uncertain Interpretation

Confirmed behavior: native 2 turns pixel measurements into pad offsets and M3
hole positions, and acknowledges roughly 0.2 mm uncertainty. Native 4 uses
pixel-derived hub length 20.75, web thickness 6.24 and an approximately 1 mm step,
while claiming exact projection agreement. Both also make engineering choices
about tap-drill representation and small details.

Hypothesis, not established geometric cause: view/section interpretation,
dimension-extension attachment, inferred axial lengths, or feature semantics
contribute to the final discrepancy. No parameter-by-parameter GT audit has been
performed here, and an unprinted dimension is not automatically inferable.

Intervention to test: retain each parameter's source region and status as printed,
derived, estimated, or unresolved; test cross-view constraints; ask for missing
information when exact reconstruction is underdetermined. A wrong interpretation
with more decimal places does not become a better specification.

## 6. Command Success, Saved Artifact And Task Completion Diverge

Native 2, recovered: the first hole-cut script rotates cylinders about incorrect
axes/pivots. The later script changes these to local X/Y-axis rotations. It is a
useful negative/repair pair, not automatically the cause of residual final error.

Native 4, recovered: initial output files reopen as zero entities and have the
same 31254-byte template size. Kimi tests saving the current working drawing,
rebuilds, and finally verifies a 140604-byte file with one Solid3d. This is a real
save-contract problem that Kimi successfully diagnoses, not its final 53.03 cause.

Native 10, incomplete recovery: the first script leaves MASSPROP's file-output
prompt unanswered. Stdout shows the pending yes/no prompt consuming `_.QSAVE` as
an invalid option, followed by a cancellation error; the job reaches its timeout.
Kimi removes MASSPROP and successfully regenerates stage1, but the overall task
times out before a complete model is delivered. The evaluator's candidate has
the same SHA-256 as stage1:
`2948eb405f39fa7fee3134ca8755c6dd37c02473d2f29dd46800d22cf09b1c6e`.
The native runner recovers a DWG when the requested final file is absent. Thus
10.78 is a salvaged partial-artifact score, not a declared finished submission.

Intervention to test: complete command prompt contracts, verify delivered DWG by
reopening, save before optional diagnostics, and distinguish completed output
from recovered partial output. Keep the unrestricted geometry interface.

## Separate Publication Failure

After EvoCAD case 2 ended, review refresh exceeded 180 seconds. The runner's
exception aborted the queue before 4/10. This cannot explain case 2's missing
geometry: it happened after modeling. Publishing should be isolated from model
execution and should not turn untouched cases into model failures.

## Implications For Training Data And The Next Experiment

- Observation-to-action and calibrated verification are candidate behavioral
  training directions; exact geometry labels still require input/GT adjudication.
- Rotation repair, save/reopen repair and the MASSPROP incident provide concrete
  tool-use examples with observable outcomes. Keep failures and successful
  recoveries distinct.
- Budget starvation, misleading feedback and publication abort are system
  regression cases. They should not become negative CAD competence examples.
- Fix and test budget allocation and telemetry before another EvoCAD/Kimi
  comparison. Retain the original failed run; a corrected run needs a new version.
- Three source parts do not establish generalization, and OmniMech 10 is already
  a validation case. Do not silently move it or its derivatives into training.

## Evidence Index

- [EvoCAD result and attempt decisions](../../evals/geometry-benchmarks/batch/evocad-kimi-k3-omnimech-2-4-10-20260916/omnimech-2/kimi-k3/result.json)
- [EvoCAD first feedback packet](../../evals/geometry-benchmarks/batch/evocad-kimi-k3-omnimech-2-4-10-20260916/omnimech-2/kimi-k3/attempts/a001/feedback-packet.json)
- [EvoCAD a001 public visual/action snapshot](../../reports/generated/kimi-vision-evocad-omnimech2-20260916-131224-579/trace.json)
- [Native 2 public trace](../../reports/generated/kimi-vision-direct-omnimech2-20260916-131138-468/trace.json): lines 66-114; first cut line 72, corrected cut line 82.
- [Native 4 public trace](../../reports/generated/kimi-vision-direct-omnimech4-20260916-131139-141/trace.json): lines 97-119 and 123-171.
- [Native 10 public trace](../../reports/generated/kimi-vision-direct-omnimech10-20260916-131139-953/trace.json): first CAD line 101, repaired job line 123.
- [Native 2 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech2-20260916/omnimech-2/kimi-k3/attempts/a001/geometry-verdict.json)
- [Native 4 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech4-20260916/omnimech-4/kimi-k3/attempts/a001/geometry-verdict.json)
- [Native 10 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech10-20260916/omnimech-10/kimi-k3/attempts/a001/geometry-verdict.json)
- [Budget and feedback implementation](../../src/cad_evoloop/evaluation/geometry_campaign.py): helper 674, allocation 1027, feedback 1495.
- [Kimi process timeout](../../src/cad_evoloop/agent/models/kimi_geometry.py): process wait 181.
- [Native partial-output recovery](../../evals/geometry-benchmarks/scripts/direct_kimi_trial.py): fallback 218.
- [Native 10 first CAD stdout](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech10-20260916/omnimech-10/kimi-k3/mcp/jobs/ef0d05dd5a0942ce8d1958c6130264cc/stdout.log)
- [EvoCAD queue status](../../evals/geometry-benchmarks/batch/evocad-kimi-k3-omnimech-2-4-10-20260916/trial-config.json)
