# Failure-Driven CAD Data: Research And Review Proposal

Status: research proposal with a subsequent executable 20-task review pilot,
2026-09-16. Scope: noncommercial research, as confirmed by the user. See
[pilot implementation and acceptance record](POSTTRAIN_PILOT.md). Twenty
candidate tasks now pass mechanical reference/counterexample checks; none has
been human-accepted for training. No benchmark split changed, and no model
evaluation or weight training was launched. Historical research-pass statements
below describe the earlier source screening, not current implementation status.

Related records:
- [Observed failures](experiments/kimi-native-bad-cases-20260916.md)
- [Source screening](FAILURE_DATA_SOURCES_20260916.md)

## IndustryForge Reading

[IndustryForge-27B](https://arxiv.org/abs/2607.28050), especially Sections
3.2 and 4.1, distinguishes model-reviewed VQA from execution-checked code.
It trains a domain model, not a complete downstream agent. Figure 2's
trajectory-recycling arrow is explicitly planned. Therefore, the paper is
useful methodology, not evidence that line-level semantic labels or a working
self-improvement environment are already available. Its COM subset drops
trajectory labels. Reusing that subset would not recover observation/action
history. These are paper claims, not independently reproduced results.

## Actual Upstream Availability

### IterCAD

The [official repository](https://github.com/KnowledgeXLab/IterCAD) contains
SFT, RL, reward-server and evaluation entry points. Its linked
[dataset](https://huggingface.co/datasets/KnowledgeXLab/IterCAD_Data/tree/main)
has six training TAR files, about 5.59 GB in total. File listings were checked
through the Hugging Face API. The card declares Apache-2.0 but has no substantive
description; the automatic dataset viewer fails to infer its archive format.
This is not evidence that the files themselves are corrupt. The initial review
checked only the listing. The subsequent bounded archive probe below confirmed
the RL manifest and some image members, but not complete GT availability or CAD
replay. Upstream rights, sample identifiers, image/code/target correspondences
and held-out split still need a complete audit.

Bounded archive probe, 2026-09-16:

- HF revision: `3a6ad3763abfd8ef2db46e0e4acf29e3b38644fe`.
- Resource: `data/train-00000.tar`, read using HTTP 206 byte ranges with a
  maximum of 8 MiB per request. No archive code was executed or files extracted.
- Parsed complete member `RL/IterCAD_RL.jsonl`, 5,668,000 bytes: 2,000 JSONL
  records, all declaring `task_type=view`.
- First record keys: `messages`, `task_type`, `images`, `gt_stl_path`.
  It has system/user messages, an image-to-code request, image reference
  `IterCAD_data/RL/images/sample_000001_img_00.png`, and GT reference
  `IterCAD_data/RL/stl/sample_000001.stl`. It is not a supervised assistant answer.
- Archive headers confirm PNG members for samples 1 through 13 in the bounded
  prefix. Reaching the read boundary is expected for this partial TAR inspection;
  it is not evidence of archive corruption. PNG decoding was not tested here.
- The referenced STL members were outside this inspected prefix. Their presence,
  validity, scaling and drawing correspondence remain unverified. SFT contents
  were not sampled in this probe, and no training-ready sample is claimed.
- A first Python networking attempt timed out. A subsequent bounded .NET HTTP
  request succeeded; the parsed results above come from the successful request.

### ComAct

The [official repository](https://github.com/KnowledgeXLab/ComAct) describes
COM-based professional-software actions and Windows VM execution. Its README
still marks the end-to-end setup guide as coming soon. The linked ComCADBench
and `comforge` paths returned 404 during this check. Do not count this as an
installed or validated environment. Licensed CAD applications remain separate
dependencies; do not redistribute their VM images as dataset assets.

## Additional Source Audit

Fusion 360 Gallery is a strong history-and-BRep source, but its
[custom license](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/LICENSE.md)
restricts use to noncommercial purposes and forbids redistribution of the entire
dataset. Portions and derivatives have additional conditions. Keep source IDs,
notices and per-source license records instead of assigning one blanket license.

### CadQuarry: A Semantic Mismatch In A Sample

The [generator](https://github.com/jacobjennings/CadQuarry) and
[data release](https://huggingface.co/datasets/jacobjennings/cadquarry) are
potential controlled-synthetic supplements, not evidence of real drafting work.
At commit `543b067ea9e416bc2e9587cb8775e012480b70ee`, its demo manifest contains
1,000 records across 15 named families.

One probe, `plate_498d66fa_0004`, describes four holes. Its
[actual program](https://github.com/jacobjennings/CadQuarry/blob/543b067ea9e416bc2e9587cb8775e012480b70ee/sample/demo-1k/parts/plate_498d66fa_0004.py)
places diameter-5.3 holes on a radius-10.2 pattern in a 33.98 x 12.4 x 4 plate.
Two centers miss the plate: 10.2 - 2.65 is larger than half its width, 6.2.
An equivalent minimal CadQuery construction printed one valid solid, eight
faces and only two cylindrical faces, volume 1508.9133247213258. The process
reported exit code 1 after printing those values; it is not a clean automated
verification pass. The geometric discrepancy is also directly calculable from
the supplied dimensions. Quarantine the description as a gold label until
reconciled; this single probe does not condemn the full dataset.

## Proposed 300-Task Mix

These are acceptance targets, not acquired or generated sample counts:

- 60 line-role tasks: visible edges, hidden edges, centerlines, dimension and
  extension lines, hatching, and genuinely overlapping roles.
- 60 dimension-to-feature tasks: anchor a value and unit to the correct edge,
  axis, hole, depth or pattern rather than merely transcribing OCR.
- 50 cross-view and section tasks: view orientation, handedness, blind/through
  features and section geometry.
- 40 observation or clarification tasks: choose a discriminating view/crop or
  request a missing dimension when the visible evidence is insufficient.
- 40 localized CAD repairs: repair a feature while preserving unrelated geometry.
- 30 projection-diagnosis tasks: distinguish an incorrect model from an
  incorrect projection, hidden-line treatment, section or registration.
- 20 complete reconstruction tasks combining the preceding skills.

Target at least 150 distinct source-part ancestries and 12 mechanical families,
with at most three accepted tasks per part. Parameter sweeps and paraphrases
do not count as independent families. Split by ancestry and template family
before augmentation; deduplicate across datasets derived from the same CAD
source. Keep OmniMech 2/4/10 as diagnostics, not training rows.

## Construction Contract

1. Acquire parts with recorded source, revision, license, units and provenance.
   Separate human-designed sources, real expert requests and synthetic parts.
2. Replay or import BRep and independently check features. Generate drawings
   through visibility-aware projection and real section operations. Preserve
   private lineage from each drawn primitive to its originating geometry or
   annotation; section-generated edges need face lineage, not invented edge IDs.
3. Generate candidate requests from observed failure families and authentic
   workflows. A language model may draft wording, not decide ground truth.
4. Validate semantic and geometric answers. CAD code running successfully does
   not establish that its description or dimensions are correct.
5. Package public input, query and resettable environment separately from
   private gold labels and verifier assets. Strip semantic IDs from public SVG
   and metadata when they would reveal the requested answer.
6. Review the first 20 tasks before scaling. Human-review request naturalness,
   label grounding and ambiguity; retain reviewer IDs, disagreements and
   adjudications. Every accepted answer needs explicit supporting evidence.

For ambiguous drawings, provide multiple consistent models or parameter ranges
and a justified clarification question. A canonical STEP file alone does not
prove that the visible input uniquely determines that shape.

## Ground Truth And Environment

Retain three kinds of truth separately:

- Geometry: BRep/STEP, units, feature dimensions, axes, topology and preserved
  regions; accept geometrically valid alternatives rather than exact code text.
- Drawing semantics: line roles, dimension anchors, view transforms, sections,
  feature correspondence and the evidence supporting each label.
- Interaction: initial state, tool contract, deterministic checkpoints, actual
  action outcomes and acceptable terminal states. Multiple plans can succeed.

An open CadQuery/OCCT environment can be the reproducible base; native AutoCAD
execution is a separately versioned Windows integration track. Each observation
must record the public intent, tool arguments, returned image hash, crop/view
transform and subsequent public conclusion. Do not require hidden reasoning.

The verifier should check validity, features, shape and preservation, plus the
task's semantic answer. State alignment conventions explicitly; do not silently
allow reflection to hide a handedness error. Check the renderer on independent
reference outputs and analytic controls. A generator and verifier sharing the
same bug do not establish gold correctness.

Provide immediate, actionable execution feedback without leaking private GT.
Keep oracle-feature-feedback experiments separately labeled. Record actual
allocated action time, process-start status and terminal status so startup or
budget failures are not mislabeled as model reasoning failures.

## Review Gate

Before the 300-task build, require a 20-task evidence pack covering the seven
families above, including original input, query, answer, label provenance,
verifier result, environment replay and a human review record. Only accepted
tasks count. This document does not claim that pack already exists.

## K3-Specific Training Decision

Research follow-up, 2026-09-16. Source:
[Kimi K3 technical report, Sections 3.1 and 4](https://arxiv.org/html/2607.24653).
It describes SFT, domain/effort RL and on-policy distillation, including visual
tool use. This is not a CAD SFT-versus-RL ablation; our recommendation below is
an engineering hypothesis, not a reported K3 result.

Starting RL from released K3 is continued domain training on an already
post-trained policy, not RL from a raw pretrained model. Neither these three
parts nor the report establishes an intrinsic model limit. In particular, the
native runs did not receive in-run GT scores. Recovered coordinate/save errors
must not be labeled as unresolved final errors, and line confusion still needs
ROI-level adjudication.

### Intervention By Failure Type

- Line semantics and evidence-to-parameter mapping: prioritize supervised
  image/ROI-to-label examples, dimension-to-feature links, and corrected replies
  conditioned on real failed states. Change annotation placement and appearance
  without changing the part as an invariance control. Also change actual geometry
  to ensure the policy remains sensitive to meaningful differences.
- Coordinate and Boolean execution: use replay-validated local repair examples,
  then short-horizon RL with feature and preservation checks. The recovered
  cylinder-axis error offers a candidate, not yet a verified training item.
- Observation selection and delayed construction: prefer outcome-based RL after
  a basic observation/action policy works. Useful crops remain allowed. A fixed
  image-count target is not the objective, and image-call count alone is not a
  measurement of wasted time.
- Lossy reprojection: first supply a validated projection/section tool and
  contrastive diagnosis examples. Do not optimize against a broken renderer.
  Include correct-solid/wrong-render and wrong-solid/correct-render controls.
- Self-consistency and overclaiming: independently test the artifact, plus
  evidence-grounded completion judgments. Self-reported confidence and volume
  calculated from the model's own mistaken assumptions do not establish truth.
- Save/protocol failures: fix deterministic tool defects first, then train
  version-specific recovery. Platform failures are censored/retried separately
  from agent-caused errors; logs must preserve that distinction.

### Proposed Terminal Reward For Modeling And Repair

This is a starting design for calibration and ablation, not an implemented or
empirically optimal reward. All quantities are computed by the private grader
from the final submitted artifact, never from claimed completion:

`R = -1` for an agent-caused missing, unreadable or invalid submission.

Otherwise, `R = 2 H + 0.5 G + 0.5 F - 0.05 C`.

- `H` is 1 only if every task-critical postcondition passes. These include
  declared tolerances, required topology and features, preserved regions for
  local edits, and the delivery/reopen contract. Otherwise it is 0.
- `G` is in [0, 1]: global shape agreement using volume overlap and bounded
  surface distance, with fixed units and task-declared pose conventions.
- `F` is in [0, 1]: feature-balanced local scores for type, count, position,
  axis, radius, depth and connectivity. Match features from geometry rather
  than trusting candidate-supplied labels. Penalize both missing and spurious
  features. Do not weight only by volume or surface area.
- `C` is in [0, 1]: capped, normalized controllable execution cost. Infrastructure
  queuing and service outages do not count as agent inefficiency. Compare with
  zero cost penalty as an ablation. A small penalty is deliberate: valid partial
  reward is at most 1, whereas a strict pass receives at least 1.95.

Partial models receive partial feedback but cannot receive the strict-pass
bonus. Evaluate what the agent submitted; do not silently substitute a better
intermediate model. Retain intermediate scores for diagnosis. Budgets remain
explicit task constraints, not an incentive to skip necessary verification.

Before training, verify that the reward ranks curated pairs correctly: missing
small hole versus correct hole, blind versus through hole, mirrored asymmetric
part, same-volume wrong shape, fake evidence, damaged unrelated geometry, and
valid intermediate versus completed deliverable. Keep these adversarial reward
tests hidden from the policy and version the evaluator separately.

### Other Task Families Need Different Answers

Do not use the modeling reward unchanged for perception or diagnostic tasks:

- Line/annotation queries: score matched primitive roles and evidence anchors;
  report class-balanced quality so common visible edges cannot hide rare-class
  errors. Accept justified overlap/multiple roles where the drawing requires it.
- Dimension queries: score values, units and the referenced feature jointly;
  transcription alone is insufficient.
- Projection diagnosis: independently label view/section/visibility errors
  versus CAD errors. A correct diagnosis may require no CAD modification.
- Clarification: reward a question that resolves a genuinely underspecified
  feature, and validate consistency after the answer. Do not make abstention a
  universal shortcut or force a unique model from insufficient evidence.
- Verification judgments: score explicit claims against recorded tool evidence.
  Optional confidence calibration can use a proper scoring rule on independently
  labeled pass/fail examples, not a reward for sounding cautious or confident.

Do not reward the presence of reflection text, number of crops, number of
iterations, or a claim of improvement. A public diagnostic interface can explain
failures while private tests determine terminal reward. Keep the verifier and
GT outside the agent's write/read scope respectively. A model judge can assist
with human-facing explanations but cannot be the sole CAD truth source.

### Small Discriminating Experiment Before Scale

Freeze the toolchain, source-family split, verifier and evaluation budgets.
Compare the unchanged checkpoint, targeted SFT only, continued RL only, and
targeted SFT followed by RL. Keep total training-compute accounting and RL
interaction counts explicit; equal gradient steps do not imply equal cost.
For the staged arm, separately compare against longer RL-only training at a
matched total budget. Repeat seeds and report uncertainty rather than choosing
the best run. Report line-role errors, local-feature success, strict completion,
unsupported completion claims, recovery success and cost, not only mean IoU.

First sample several attempts on atomic tasks to measure reward variation. If
nearly every attempt gets the same failing reward, use clearer supervision,
shorter tasks or denser validated feature rewards. If good actions already
occur but selection is unreliable, RL-only is a credible competitor. Failure
to sample a solution is not proof the model can never produce one.

Our API/CLI evaluation setup does not update K3 weights. Actual SFT/RL requires
a trainable checkpoint and training resources, or an explicitly supported
provider training channel. No such training was configured or started here.

## Acquisition And Environment Order

The near-term source order is IterCAD for existing task/program assets, Fusion
360 Gallery for independently inspectable geometry/history, and neuralCAD-Edit
for authentic expert requests. Prefer holding neuralCAD-Edit out as an external
realism check; do not train on its requests and still present its benchmark score
as held-out performance. Account for its Fusion Gallery ancestry when splitting.

Full line-role and dimension-anchor truth is an additional deliverable, not an
assumed field in these releases. Generate controlled drawings with private
semantic provenance, then independently verify rendering and human-review the
labels. Use real drawings to check transfer beyond our generator's styles.

### Environment Roles

Keep three components separate:

1. Task/agent sandbox: only public drawings, requests, initial code where
   applicable, and a writable episode workspace. Expose image inspection,
   arbitrary code execution within the sandbox, CAD actions, checkpointing and
   submission. Do not prescribe the geometric solution or require one unique
   construction sequence.
2. CAD worker: executes and renders with pinned libraries and resource budgets.
   Use CadQuery/OCCT in Linux sandboxes for the batch geometry track. Use dedicated
   licensed Windows workers for AutoLISP/COM, native DWG delivery and recovery.
   CadQuery success does not prove AutoCAD command proficiency.
3. Private grader: receives the submitted artifact and has access to GT and
   hidden checks. Do not mount its files into the agent sandbox. A folder named
   `private` inside an agent-readable workspace is not isolation. Expose only
   the approved diagnostic response, not GT file paths or arbitrary grader code.

Reset between episodes, not between turns: long-horizon work requires persistent
files and CAD state within an episode. Bind checkpoints, operation receipts,
images and verdicts to the episode and attempt. Reconcile uncertain CAD side
effects before retrying. An AutoCAD watchdog may manage only its owned dedicated
worker, never an unrelated interactive user session. Serialize each native CAD
session; scale with independent workers rather than competing COM calls.

First validate one episode and replay, then bounded concurrency. Preserve raw
stdout/stderr, tool arguments/results, image bytes/hashes, allocated action time,
process-start status and final artifact hashes. Separate infrastructure outages
from agent-caused errors. Reuse EvoCAD's event/artifact/review mechanisms, while
auditing its current runtime boundary before treating it as an RL environment.

### Reuse Before New Infrastructure

[IterCAD's evaluation adapter](https://github.com/KnowledgeXLab/IterCAD/blob/main/eval/README.md)
and [reward-server entry point](https://github.com/KnowledgeXLab/IterCAD/blob/main/train/IterCAD_Reward_Server.sh)
provide concrete execution/render/reward integration references. Their code has
been inspected, not installed or security-audited. Pin and test it before reuse;
subprocess isolation alone is not an adequate security boundary for arbitrary
agent code.

[AgentENV](https://github.com/kvcache-ai/AgentENV) is a later scaling option, not
necessary for the first 20 reviewed tasks. It provides distributed Firecracker
sandboxes and snapshot/resume capabilities. Its documented prerequisites include
Linux kernel 6.8+ and KVM access. It is not a drop-in native Windows AutoCAD host.
No platform installation or native-worker provisioning happened in this pass.

## Closed-Model Disclosure Boundary

The checked [Anthropic transparency documentation](https://www.anthropic.com/transparency)
describes broad training sources and post-training. Its
[Fable launch page](https://www.anthropic.com/news/claude-fable-5-mythos-5)
demonstrates CAD use, but does not provide a CAD-specific training recipe.
The checked [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
and [developer workflow article](https://developers.openai.com/blog/architectural-visualization-with-astra)
likewise do not establish a reproducible CAD curriculum, data mixture, reward
definition or training ablation. This is a bounded disclosure finding, not proof
that either vendor did no CAD-specific training. A demo, model score, or generic
fine-tuning guide is not disclosure of a model's actual CAD training procedure.
