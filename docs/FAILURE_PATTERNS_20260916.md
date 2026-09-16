# Failure Cases Before Data Collection

Status: evidence review draft, 2026-09-16. This is a failure inventory and a
data-search brief, not an implemented training pipeline or a causal model ranking.

## Scope And Artifacts

The extracted [inventory](../reports/generated/failure-mining-20260916/inventory.json)
contains 17 strict-failure run records across eight distinct geometry problems,
four selected BenchCAD cases, three existing human reviews, complete per-attempt
metrics/recorded decisions, and SHA-256 references to 145 local source files.
Repeated runs of one problem are evidence about that problem, not new problems.

Selection covers the 30-case Sol V2 campaign (8 strict failures), the 30-case
native-feedback V3 campaign (4 strict failures), native Codex Sol/Astra on
OmniMech 2 (2 failures), and native Kimi on OmniMech 2/4/10 (3 failures).
This deliberately scoped inventory does not claim to include every historical
pilot, provider incident, or unsuccessful intermediate checkpoint in the repo.

The geometry score is a continuous score on 0-100; strict pass is a separate
conjunction of watertightness, IoU >= 0.99, normalized Chamfer <= 0.006,
bbox relative error <= 0.002, and volume relative error <= 0.005. BenchCAD
numbers below are official voxel IoU on 0-1 and must not be averaged with it.

The full eight-case V2 failure list is OmniMech 2/4/6/9/10 and Ortho2CAD
00186338/00241318/00694405. V3 retains failures on OmniMech 2/4/9 and
Ortho2CAD 00186338. The JSON preserves all of these, including near-threshold
cases that are not yet assigned a training label.

## Six Data Directions

### 1. Cross-View And Section Interpretation

Observable problem: assembling plausible individual views into the wrong 3D
arrangement; confusing a section boundary with a mounting feature; incorrect
handedness, depth, feature side, or variant selection.

- OmniMech 2 / native Astra: 91.69. A human-requested whole-solid mirror gives
  100 under the unchanged verifier. This confirms a mirror relationship against
  GT, not which source convention is authoritative. Input-view adjudication is
  still necessary before labeling the original answer wrong-handed.
- OmniMech 2 / EvoCAD Sol V3: 72.92 after ten attempts. Its recorded decisions
  repeatedly revise B-B rail transitions, mounting-ear bands and M3 locations;
  the best checkpoint has accurate global measurements but wrong local shape.
- OmniMech 9 / EvoCAD Sol V3: the a002 decision identifies a 190 mm/two-carriage
  interpretation instead of the 40 mm/one-carriage target. Its next score rises
  from 9.29 to 74.09. This is a useful task-variant/structure interpretation case;
  the model's narrative is not an independent geometric annotation.

Data to seek: paired orthographic/section drawings and exact CAD, with declared
view axes, projection convention, variant identity and asymmetric features.
Natural queries should ask for reconstruction or locating a specific feature;
labels can include cross-view correspondences and final CAD.

### 2. Feature Semantics And CAD Construction

Observable problem: replacing an engineering feature with an inadequate primitive,
placing holes incorrectly, or creating degenerate/coincident Boolean boundaries.

- OmniMech 4 / Sol V2: 99.40 but IoU 0.972953. The existing human review flags
  incorrect teeth and holes, and suspects dashed-line interpretation. Geometry
  error is human-supported; the dashed-line explanation remains a hypothesis.
- OmniMech 4 / Sol V3: cylindrical tooth approximations, M6 termination, keyway
  coincidence and tooth-edge taper recur in the recorded repairs. a002 = 94.15,
  a003 = 84.14, selected a006 = 99.77; improving one check does not validate the
  whole feature. Native Astra's separate 100 run provides a successful comparison,
  not a unique reference construction sequence.
- Kimi / OmniMech 4: 53.03, IoU 0.793316, volume error about 6.53%. This is a
  genuine GT discrepancy; a specific cause still needs feature-level inspection.

Data to seek: sketches/profiles, holes, slots, thin walls, fillets/chamfers,
repeated patterns and Boolean feature histories paired with native CAD. A STEP
file is geometric GT, not automatically an editable parametric feature history.

### 3. Local Repair And Change Validation

Observable problem: naming the error region without applying the intended change,
editing in the wrong frame, or improving one part while breaking another.

- OmniMech 4 / Sol V3: a005 leaves the score unchanged at 99.75; the agent reports
  a no-op and retries in native coordinates. Later tooth-phase changes produce
  99.47 and then 63.16 before recovery. The no-op cause is agent-reported;
  the score sequence and regression are recorded facts.
- Ortho2CAD 00186338 / Sol V3: a006 = 98.58 -> a007 = 64.54, followed by a stated
  world-coordinate recovery. a011 and a012 both score 99.15; the agent reports
  another no-op and requests a more penetrating cutter.

Data to seek: before-CAD + localized observation + edit request + after-CAD.
The label must test both the requested change and preservation of unaffected
features. Real failed/successful checkpoint pairs are preferable to arbitrary
mesh corruption; any synthetic perturbation must remain CAD-valid and labeled.

### 4. Verification And Checkpoint Selection

Observable problem: following a proxy score that orders candidate quality wrongly,
or submitting a worse checkpoint despite having produced a better one.

BenchCAD provides particularly clear controls because official GT scores were
computed after the run and were not available to the agent:

- rect_frame_000285_s20260505: best official IoU 0.805492 at iteration 4;
  final 0.268497. The documented thinning edits improve the image proxy while
  damaging the solid.
- sprocket_013310_s20260505: official IoU 0.359555 -> 0.239270 while image IoU
  rises from 0.619725 to 0.669409.
- duct_elbow_008189_s20260505: first official IoU 0.495385, best 0.560128,
  final 0.470834; image IoU rises from 0.768849 to 0.869409.
- table_004846_s20260505: best official IoU 0.759774, final 0.597249. This is
  checkpoint-selection regret, not a final-vs-first regression.

Data to seek: near-matching silhouettes with different thickness, cavities or
depth, plus exact 3D labels; candidate comparisons with identical input and
budget. A higher aggregate score alone does not make a valid preference pair.
Query-visible evidence must support the requested comparison.

### 5. Observation, Execution And Recovery Budget

Observable problem: extended observation without timely executable checkpoints,
then insufficient time to complete/recover and verify the model.

- Kimi / OmniMech 10: 10.78, 5400.078 seconds, `time_budget`. The complete event
  stream contains 25 ReadMediaFile calls, all before the first CAD start at line
  101. This is 25 calls, not 25 unique images or a measurement of attention.
- The MCP log records two Core Console starts: the first reaches its 300-second
  timeout, the second succeeds with a partial solid. Therefore this is neither
  "never called CAD" nor exclusively a visual-perception failure.
- Kimi / OmniMech 2 and 4: 88.96 / 53.03 after 4456.125 / 3355.755 seconds;
  complete tool-call counts are 27 / 21 image reads. Earlier partial observations
  must not be mistaken for complete call counts.

All three Kimi direct runs had no in-run GT score feedback. They cannot support
the label "ignored the low verifier score". Sequence position does not establish
wall-clock time per image when CLI events lack timestamps.

Data to seek: executable tasks with staged checkpoints, native logs, recoverable
failures and validated final output. Image/CAD pairs alone cannot teach this
behavior; collect observable action/state trajectories. Quality still matters:
quickly constructing the wrong solid is not the positive target.

### 6. Missing Information And Expert Clarification

Observable problem: a task cannot justify exact GT parameters from visible input.
The training target should identify the missing constraint and ask a useful
question, with a recorded expert answer when exact reconstruction is required.

- Ortho2CAD 00241318 / Sol V2: 98.11. The existing human review explicitly
  identifies the missing first-step height and asks for a clarification behavior.
- Ortho2CAD 00186338: ordinary recovery selects 99.25 after 14 attempts; exact
  unordered features and ordered plans both give 100 on the first attempt.
  However, three input audits found only three printed overall dimensions.
  Only 3 of 29 descriptive GT values match those labels. These values include
  dependent coordinates, so this fraction is not a degrees-of-freedom count.
  Oracle success demonstrates execution capability with extra information;
  agent-versus-model attribution remains confounded by missing specification.

Data to seek: fully dimensioned drawing/CAD pairs as controls, and deliberate
missing-dimension variants paired with precise clarification questions and
expert responses. Keep the two task types distinct and retain input provenance.

## Separate System Incidents

Ortho2CAD 00694405 / Sol V2 stops at 99.28 with `decision_unavailable` and a
FileNotFoundError. It contains both an imperfect candidate and a runtime-censored
repair opportunity. Network retries, unavailable dependencies, postrun export
incidents and invalid verifier assumptions belong in system diagnostics until
there is enough evidence to assign responsibility. They are not automatically
negative geometry-training labels.

## What The Data Search Must Deliver

Search against these six directions, rather than a target row count alone.
For each candidate source record what is actually downloadable: original images,
STEP/B-Rep, source programs, feature histories, edit pairs or execution traces.
Also record whether the images are native drawings or must be rendered from CAD,
and whether the promised exact answer is available for the downloaded samples.

The local 50-case manifest currently has 50 available STEP files and input images,
but only 40 registered ground-truth programs (Ortho2CAD). The ten OmniMech records
have STEP/STL and no registered construction code. Do not promise GT trajectories
for all 50, or treat regenerated renders as original real-world drawings.

OmniMech 10 is in the existing validation split. Its failures can motivate this
diagnostic brief; it and its derivatives must not silently become training rows.
Any future split follows source-part/variant ancestry, not individual images or
paraphrased queries. Near-duplicate views do not establish diversity.

First output should be 10-20 reviewed source-grounded examples across these
directions. Hundreds are a later goal, contingent on distinct source parts,
GT availability and verified labels. The current 17 run records are not 17
ready-to-train examples.

## Reproduction And Evidence

Primary Kimi follow-up: [native Kimi Code + K3 bad cases](experiments/kimi-native-bad-cases-20260916.md)
analyzes OmniMech 2/4/10, recovered intermediate errors, residual failures and
mapping to the proposed training-example fields. EvoCAD incidents are separate.

Follow-up: [Kimi failure pattern audit](experiments/kimi-failure-patterns-20260916.md)
adds the completed EvoCAD/Kimi OmniMech 2 run and audits the native Kimi traces.
It confirms a one-second recovery-action budget defect, distinguishes unsupported
reflection narratives from observed actions, and separates recovered CAD errors
from residual geometric failures. The earlier 17-run inventory is unchanged.

```powershell
E:\python\python.exe evals/geometry-benchmarks/scripts/extract_failure_inventory.py `
  --output reports/generated/failure-mining-20260916/inventory.json
```

The extractor refuses to overwrite an existing snapshot. Use a new output path
for a new extraction. It reads stored results only; no model or CAD execution.

- [Machine-readable inventory](../reports/generated/failure-mining-20260916/inventory.json)
- [Human reviews](../evals/geometry-benchmarks/human-reviews/agent-geometry-30-sol-v2.jsonl)
- [Mirror intervention](experiments/astra-omnimech2-mirror.md)
- [GT attribution record](../evals/geometry-benchmarks/reference-runs/gt-attribution-00186338-r1.json)
- [BenchCAD analysis](../reports/generated/benchcad/sol-family-30-v2/analysis.json)
- [Kimi 2 review](http://127.0.0.1:8770/?view=direct-kimi-2)
- [Kimi 4 review](http://127.0.0.1:8770/?view=direct-kimi-4)
- [Kimi 10 review](http://127.0.0.1:8770/?view=direct-kimi-10)
