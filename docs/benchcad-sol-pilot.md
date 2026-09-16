# EvoCAD / GPT-5.6 Sol BenchCAD pilot

## Result

EvoCAD reconstructed all four public Vision2Code smoke records with GPT-5.6 Sol
at medium reasoning. Final programs were scored after explicit Agent submission
using BenchCAD's pinned 64-cubed voxel IoU and composite implementation.

| record | iterations | voxel IoU | composite |
| --- | ---: | ---: | ---: |
| washer | 1 | 0.967154 | 0.947000 |
| hex nut | 3 | 1.000000 | 0.999400 |
| spacer ring | 8 | 0.995558 | 0.997300 |
| bolt | 6 | 0.893742 | 0.936200 |
| **mean** | **4.5** | **0.964114** | **0.969975** |

All four submitted and executed. The mean-IoU 95% t interval is approximately
0.886 to 1.000 after clipping to the metric range; n=4 is too small for a
leaderboard claim.

## Public references

OpenAI reports GPT-5.6 Sol at 0.706 without tools and 0.834 with a Python tool:
https://openai.com/index/gpt-5-6/

BenchCAD describes Vision2Code as execution-grounded 64-cubed voxel IoU and
publishes its reproducibility interface:
https://github.com/BenchCAD/BenchCAD-main

BenchCAD's open agentic harness PR reports Grok 4.5 at 0.3194 single-shot and
0.7667 agentic on a fixed 299-record public subset:
https://github.com/BenchCAD/BenchCAD-main/pull/53

The EvoCAD smoke mean is numerically 0.130 above OpenAI's 0.834, but the samples,
reasoning setting, round semantics, and execution isolation differ. It is a
pipeline sanity check, not evidence that EvoCAD beats the published Sol system.

## Reproducibility boundary

- BenchCAD upstream: `dfe51280de93adfba9b233d89bc32dfb223a22f9`
- Dataset revision: `5919f578ab09ec283603a082fab07c7639ab56eb`
- EvoCAD condition: local audited process, no Docker
- Candidate feedback: target/candidate images only; no GT geometry
- Final evaluation: hidden GT STEP/code, official BenchCAD functions
- Safety ceiling: 12 EvoCAD iterations; the Agent stopped at 1, 3, 8, and 6

Raw trajectories and generated evidence live under
`reports/generated/benchcad/sol-official-smoke-v2/`.

## Family-diverse 30-record result

The formal pilot uses one deterministic record from each of 30 distinct
families. All 30 records produced a valid submitted STEP and received the pinned
BenchCAD 64-cubed voxel score.

| condition | mean IoU | bootstrap 95% CI |
| --- | ---: | ---: |
| first EvoCAD checkpoint | 0.602363 | [0.490910, 0.709437] |
| submitted EvoCAD checkpoint | 0.741202 | [0.651506, 0.828017] |
| post-hoc oracle checkpoint | 0.777236 | [0.697561, 0.853925] |

The paired final-minus-first uplift is 0.138839 with bootstrap 95% CI
[0.048645, 0.235799]. Twenty-three records improved, four tied, and three
regressed. The mean checkpoint-selection regret is 0.036034; the submitted
checkpoint is post-hoc optimal on 16 of 30 records. This makes the current
priority concrete: preserve the useful feedback loop while improving the
verifier and stopper so later image gains cannot erase stronger 3D geometry.

The campaign generated 224 scored candidate checkpoints over 32,621.54 summed
record-seconds. Recorded action and decision turns used 109,877,618 input
tokens, of which 102,796,800 were cached, plus 532,856 output tokens. IR-builder
usage is not included in those token totals.

OpenAI's published Sol results are 0.706 without tools and 0.834 with a Python
tool. EvoCAD is numerically 0.035202 above the former and 0.092798 below the
latter. These are descriptive differences only: this pilot is a family-diverse
30-record sample with medium reasoning, 12 EvoCAD iterations, and local audited
process isolation, not a confirmed reproduction of the vendor split and
harness.

Machine-readable results, per-case CSV, post-hoc checkpoint scores, and
paper-ready PNG/PDF figures live under
`reports/generated/benchcad/sol-family-30-v2/`.

## Failure attribution

The final image-only score correlates with hidden voxel IoU (Pearson 0.855710,
Spearman 0.846145), but the remaining mismatch is consequential. The three
final regressions are not failures to consume feedback; they optimize feedback
that is incomplete for hidden 3D structure:

- `rect_frame`: reducing thickness raised image IoU from 0.558 to 0.583 but
  collapsed official IoU from 0.805 to 0.268.
- `sprocket`: progressive bore and thickness edits raised image IoU from 0.620
  to 0.669 while official IoU fell from 0.360 to 0.239.
- `duct_elbow`: wall-thickness edits raised image IoU from 0.837 to 0.869 while
  official IoU fell from 0.560 to 0.471.

An image-score ratchet alone would preserve these errors because its ordering
is wrong. The next verifier should estimate hidden-volume risk from feature
semantics, multi-view edge/depth evidence, and parameter sensitivity, then keep
a Pareto archive rather than selecting solely by silhouette IoU. Human review
should start with `rect_frame`, `sprocket`, `duct_elbow`, and `table`, the four
largest checkpoint-selection regrets.
