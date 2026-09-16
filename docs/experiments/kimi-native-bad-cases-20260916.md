# Native Kimi Code + K3: Bad Case Analysis

Date: 2026-09-16. Primary scope is the native Kimi Code harness, not EvoCAD.
Source: existing public text, tool I/O, images returned to the agent, CAD scripts,
and post-run geometric verdicts. No new model calls or CAD execution.

## Three Cases

### OmniMech 2: Plausible Model, Incorrect Spatial Occupancy

Final score 88.96, IoU 0.887791. Watertightness and bounding box pass; volume
error is only 0.2032%. This is not simply a wrong overall scale or missing file.
Global measures are close while local shape/spatial occupancy does not match.
The exact residual feature attribution remains unverified.

27 image calls return 27 distinct images. Kimi calibrates pixels, extracts lines
and holes, summarizes dimensions, then performs four Core Console jobs and two
topology exports. It does real modeling and checking, not just image inspection.

The first cut script has a concrete coordinate error: a Z-axis cylinder intended
to cut an X-axis hole is rotated around Z, which cannot change its axial
direction. Some other holes also use inappropriate shared rotation pivots. The
later script fixes the local rotation axes/pivots and rebuilds from the body.
This is a recovered intermediate error, not proof of the final mismatch cause.

Public completion text claims exact projection agreement, but also acknowledges
pixel-estimated pad offsets, hole rows and ambiguous dimensions. Checks of body
bounds, volume and feature presence are not sufficient to support exact matching.

Primary patterns: coordinate-frame errors; uncertain image interpretation turned
into fixed coordinates; stronger verification claims than the evidence supports.

### OmniMech 4: Self-Consistent Wrong Geometry, Plus A Recovered Save Error

Final score 53.03, IoU 0.793316; volume error 6.5328%, bbox error 0.5723%.
The delivered DWG is a valid solid, not the empty intermediate file.

21 image calls return 21 distinct images. Kimi builds a revolved sprocket profile,
patterns 24 tooth gaps, cuts a keyway and radial hole, and checks topology. It
estimates undimensioned lengths/thicknesses from pixels. Its own volume estimate
of about 81100 mm^3 agrees with the constructed 81124 mm^3, but not with GT.
The same interpretation supplies both the construction and analytic check, so
agreement does not independently validate that interpretation.

Initial save jobs produce blank-template DWGs. Reopening reveals zero entities;
Kimi investigates, tests saving the current working drawing, rebuilds and verifies
the final one-solid DWG. This recovery is positive evidence, not an explanation
for the final geometric score. A specific tooth/section/M6 error must not be
declared the primary residual cause without localized comparison and input audit.

Primary patterns: interpretation uncertainty; self-consistency mistaken for
reference correctness; misunderstanding the tool's save contract, later repaired.

### OmniMech 10: Observation, Command Failure, Then Incomplete Recovery

Final score 10.78, IoU 0.163514; the 5400-second process budget expires.
All 25 image reads (25 distinct images) precede the first CAD call. Public
messages repeatedly seek another crop, pixel measurement or ASCII interpretation
before the first base checkpoint is constructed. Image calls alone do not show
how much wall time was spent on each observation or whether each was useful.

The first Core Console script builds the base but leaves the MASSPROP file-output
question unanswered. Its stdout shows `_.QSAVE` consumed as an invalid response,
then a cancellation error; the job times out. Kimi identifies the command issue,
removes MASSPROP and successfully builds stage1. The overall run nevertheless
expires without the complete part.

The native runner salvages an intermediate DWG when the requested candidate is
missing. The scored candidate is byte-identical to stage1. Thus this is not a
finished wrong answer voluntarily submitted as complete, and not evidence that
Kimi ignored the error. It attempted recovery but did not finish the task.

Primary patterns: no early executable checkpoint; incomplete noninteractive
command protocol; recovery cost left insufficient completion time.

## Human Review: Line Semantics And Pixel-Driven Reprojection

Human observation, 2026-09-16: the user reviewing native Kimi's image records
reports confusion between hidden/dashed lines, dimension lines and physical
geometry, as well as excessive pixel-based investigation and 3D-to-2D comparison.
This is recorded as human-reported semantic confusion, not yet a per-line gold
annotation or a proven explanation of every final geometry mismatch.

The stored scripts establish concrete supporting mechanisms:

- Native 2, event lines 34-44: thresholds split blue pixels from dark pixels;
  the dark mask is called "geometry only". Hough segment extraction and merging
  output coordinates, and derived grids are called cleaned geometry masks.
  These helpers do not classify visible boundaries, hidden edges, centerlines,
  dimension/extension lines, or section hatching. Kimi does mention centerlines
  and inspect blue dimensions, so this is not evidence of zero awareness of line
  types; the extracted representation does not reliably encode their semantics.
- Native 2, line 100: all extracted straight/circular topology edges are plotted
  with the same solid style in XY and ZY. There is no hidden-line classification,
  no section-plane operation, and no registration/overlay with the input image
  in this plotting script. Its returned image is read at image call 27, line 102;
  line 104 then claims exact agreement. A wireframe side projection is not a
  computed B-B section. Inspecting a separately rendered image can support visual
  comparison, but it is not an actual source-image overlay.
- Native 4, lines 105/107: unsupported curves are initially replaced with the
  line joining their bounds' minimum and maximum points. That line is not a
  faithful curve representation. At line 111 those curves are omitted instead,
  after a public request to remove plotting artifacts. The resulting simplified
  side views still do not classify visible/hidden edges or compute a section.
  This is an additional lossy observation step, not proof of a bad CAD Boolean.

Important distinctions:

- A hidden edge can represent real geometry. Its role differs from a visible
  boundary; it should not simply be removed. Dimension and extension lines carry
  measurement relations, not extra solid edges. Line style alone is insufficient
  without view, feature and annotation context.
- Cropping and calibrated pixel measurements can be useful. More accurate pixel
  coordinates cannot resolve whether a line is an edge, annotation or section
  convention. Measurement uncertainty and drawing scale must remain explicit.
- Reprojection is a valid check when projection, visibility, section semantics,
  curve geometry and coordinate registration are correct. The bad pattern is
  treating a lossy, semantically different wireframe as equivalent evidence.
- Native 2 has one recorded final model-view image read, not an established long
  repeated CAD optimization loop. Native 4 re-plots its topology views. These
  records do not establish repeated pixel-loss-driven geometry optimization.

Additional training targets: `line_semantics_confusion`,
`pixel_measurement_before_semantic_resolution`, and
`lossy_reprojection_as_verification`. The first includes human-reported error;
the latter two describe observed methods and risks, not automatic failure labels
for every measurement or projection call.

For a line-understanding query, annotate the source ROI, view identity, visible
line style, semantic role, referenced feature/dimension endpoints, and supporting
cross-view evidence. For a reprojection query, provide the actual candidate and
input view; label the projection/section setup and which discrepancies are CAD
errors versus drawing-annotation or visualization differences. A useful control
changes annotation placement without changing the part: reconstructed geometry
should remain unchanged. These are proposed examples, not validated data yet.

## Seven Pattern Families For Data Preparation

1. Drawing-line semantics. Separate visible boundaries, hidden geometry,
   centerlines, measurement annotations and section hatching using context. A
   dark-pixel or segment mask is not a semantic geometry representation.
2. Observation must resolve a specific modeling uncertainty. Use the native 10
   sequence to study when an additional crop changes a feature hypothesis versus
   postponing construction. No arbitrary crop-count limit is a ground truth.
3. Evidence-to-parameter attribution. Native 2/4 expose printed versus estimated
   numbers and interpretation choices. Gold perception answers need source-region
   references, view axes, dependencies and explicit unresolved constraints.
4. Intent-to-CAD coordinate execution. Native 2's wrong-axis/correct-axis cut is
   an actionable failure/repair pair. Check resulting hole axis, location, depth
   and preservation of unrelated geometry, not just command success.
5. Tool protocol and artifact completion. Native 4's save/reopen sequence and
   native 10's MASSPROP failure have concrete tool-level evidence. Gold actions
   must follow the exact tool version's contract and produce an independently
   reopenable solid; model-in-memory state is not sufficient.
6. Faithful reprojection. Verify view/section identity, visibility, curve fidelity
   and registration before comparing pixels. Do not compare an all-edge wireframe
   directly with a section drawing as if their lines had identical meaning.
7. Independent verification and calibrated completion. Native 2/4 show that
   bounding-box/volume checks and a plausible projection can coexist with a GT
   discrepancy. Gold verification should include source-grounded feature checks,
   appropriately qualified uncertainty and consistent geometric scoring.

These are observed behaviors across three parts, not a demonstrated intrinsic
limit of K3. All three runs lacked in-run GT feedback. "Ignored a low score" and
"could not repair a localized verifier mismatch" are unsupported labels here.

## Mapping To The Proposed Example Schema

- `input`: original task drawing and task.json; include any crop transform and
  exact returned image hash. A repair query also needs the before-CAD and logs.
- `query`: distinguish full reconstruction, interpreting one feature, repairing
  one CAD operation, diagnosing a save failure, and evaluating a candidate.
- `perception_answer`: independently reviewed dimensions, view mapping, line
  semantic roles, feature constraints, evidence regions, and unresolved values.
  Do not copy Kimi's
  dimension summary into this field as a gold answer.
- `planning_answer`: validated construction dependencies, Boolean relationships,
  recoverable stages and targeted checks. Multiple correct plans can exist.
- `cad_action_answer`: verified executable operations and observable outcomes.
  Native 2/4 offer recovered local sequences; replay and geometric preservation
  checks are still required before calling them gold training examples.
- `groundtruth`: canonical dataset CAD plus provenance/hash. STEP geometry does
  not itself provide a canonical AutoLISP or CADQuery trajectory. The local
  OmniMech records have no registered GT construction programs.
- `bad_pattern_tags`: the seven families above, with observed versus hypothesized
  attribution and recovered versus final error status.
- `verifier`: task-specific postconditions plus declared geometry thresholds.
  Existing strict checks require watertightness, IoU >= 0.99, normalized Chamfer
  <= 0.006, bbox error <= 0.002, and volume error <= 0.005. Do not apply full-part
  thresholds as the only validator for a narrow tool-repair exercise.

The most concrete initial examples are the native 2 cylinder-axis repair, native
4 save/reopen repair, and native 10 command-prompt diagnosis. Native 2/4 final
shape errors need feature-level human adjudication before exact perception labels.
Three parts cannot supply hundreds of diverse examples by paraphrasing. OmniMech
10 and its derivatives must retain their existing validation-split ancestry.

## Evidence And Review

- [Native 2 visual and operation record](http://127.0.0.1:8770/kimi-vision-direct-2.html)
- [Native 4 visual and operation record](http://127.0.0.1:8770/kimi-vision-direct-4.html)
- [Native 10 visual and operation record](http://127.0.0.1:8770/kimi-vision-direct-10.html)
- [Native 2 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech2-20260916/omnimech-2/kimi-k3/attempts/a001/geometry-verdict.json)
- [Native 4 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech4-20260916/omnimech-4/kimi-k3/attempts/a001/geometry-verdict.json)
- [Native 10 verdict](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech10-20260916/omnimech-10/kimi-k3/attempts/a001/geometry-verdict.json)
- [Native 2 extracted public trace](../../reports/generated/kimi-vision-direct-omnimech2-20260916-131138-468/trace.json): cut line 72; corrected cut 82; completion 114.
- [Native 4 extracted public trace](../../reports/generated/kimi-vision-direct-omnimech4-20260916-131139-141/trace.json): volume 97-99; empty output 123-142; recovery 148-171.
- [Native 10 extracted public trace](../../reports/generated/kimi-vision-direct-omnimech10-20260916-131139-953/trace.json): first CAD 101; recovery 123.
- [Native 10 failed command stdout](../../evals/geometry-benchmarks/batch/direct-kimi-k3-omnimech10-20260916/omnimech-10/kimi-k3/mcp/jobs/ef0d05dd5a0942ce8d1958c6130264cc/stdout.log)
- [Separate EvoCAD/system audit](kimi-failure-patterns-20260916.md): not part of this native failure attribution.
