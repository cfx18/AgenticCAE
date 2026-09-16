# Data Sources Matched To Observed Failures

Status: first source screening, 2026-09-16, following the
[failure inventory](FAILURE_PATTERNS_20260916.md). Dataset descriptions below
are publisher claims checked against their current repositories. Downloaded
format probes are identified separately from accepted training examples.

Follow-up: [noncommercial research constraints, IndustryForge/IterCAD audit,
and a proposed 300-task mix](POSTTRAIN_DATA_REVIEW_20260916.md). This follow-up
records candidate resources and a semantic-label mismatch found in one
CadQuarry sample; it does not count them as accepted training data.

## First Priority: Feature And Edit Evidence

### Fusion 360 Gallery

Best fit: feature construction, Boolean semantics, intermediate checkpoints and
local edit validation. Autodesk publishes 8,625 reconstruction sequences, with
JSON construction data, STEP/SMT geometry and thumbnails. Reconstruction is
limited to sketch/extrude; this subset alone is not a complete library of gear,
thread, fillet and advanced-feature histories. The segmentation subset is a
separate resource and should not be conflated with executable sequences.
Sources: [official repository](https://github.com/AutodeskAILab/Fusion360GalleryDataset),
[format specification](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/docs/reconstruction.md).

Acquired locally: the official `Couch.json` / `Couch.step` test fixture, README,
license and reconstruction specification, pinned to repository commit
`1084b881f3bb710267801d812d6e9286b8667059` with file SHA-256 values in
[download manifest](../.local/datasets/evocad/source-screening-20260916/fusion360-gallery/download-manifest.json).
This is one format probe, not a mechanical training example or a validated
image/query/GT pair. CAD replay and input generation remain to be checked.

### neuralCAD-Edit

Best fit: realistic user requests, localized edits and before/after preservation.
The official release describes 192 multimodal requests and 384 edits from ten
expert CAD designers, with automatic, human and VLM evaluations and model
outputs. Real expert requests are valuable for query realism; model-generated
outputs in the release must not be used as expert ground truth by default.
Sources: [project](https://autodeskailab.github.io/neuralCAD-Edit/),
[official code](https://github.com/AutodeskAILab/neuralCAD-Edit).

The [actual file listing](https://huggingface.co/datasets/autodesk/neuralCAD-Edit/tree/main)
contains `edit_192_external.zip`, about 6.03 GB, and marks the dataset CC BY-NC-4.0.
HF revision checked through its API:
`b29220c3ccceecd9188ab42f1688e4e6bf5d7a7d`.
The archive has not been downloaded in this pass. The repository's small example
folder is a named Gemini output, not an independently verified expert edit pair.
Next inspection must identify initial model, exact request, expert target,
alternative acceptable edits and evaluation annotations inside the full release.

## Second Priority: View Correspondence

### Drawing2CAD

Best fit: front/top/right correspondences and the link from projected curves to
CAD sequences. The official ACM MM 2025 repository describes four SVG views,
vectorized view arrays and HDF5 CAD sequences, derived from DeepCAD, and links
its drawing-export pipeline. These are CAD-derived drawings, not scanned
industrial blueprints. The README does not establish full dimension annotation;
do not assume they resolve the missing-dimension issue in our Ortho2CAD cases.
Source: [official repository and download link](https://github.com/lllssc/Drawing2CAD).

Status: documentation and download route checked; no dataset archive acquired.
Use source-part lineage to deduplicate against DeepCAD-derived sources.

### TriView2CAD / CReFT-CAD

Best fit: dimension-to-feature mapping, view consistency and parameter questions.
The authors describe a 15-parameter bridge-pier domain with PNG, DXF, JSON,
scripts and STEP/B-Rep, and link a ModelScope dataset. This could provide a
useful fully specified control, but bridge-pier variants do not replace diverse
mechanical parts. The repository also retains a release-upon-acceptance notice,
so file-level availability requires direct inspection rather than inferring it
from the headline sample count.
Source: [author repository](https://github.com/KeNiu042/CReFT-CAD).

Status: source and claimed modalities located; actual sample payloads and their
GT correspondences remain unverified. Not counted as acquired data.

## Scale Supplements

- [DeepCAD](https://github.com/rundiwu/DeepCAD): existing construction-sequence
  source for scalable shape/parameter controls. Drawings, realistic edit requests
  and task-specific labels still need to be generated or sourced; the original
  operation vocabulary limits which bad patterns it can cover.
- [CAD-Editor](https://github.com/microsoft/CAD-Editor): official ICML 2025 code
  and a synthetic paired-CAD/edit-instruction generation pipeline. A candidate
  for controlled edit diversity; its synthesized requests must retain that label.
- [Ortho2CAD](https://github.com/AdityaJoglekar/Ortho2CAD): already relevant to
  the local failures and available locally in part. More rows do not by
  themselves address underspecified drawings; inspect dimension coverage per
  target feature before assigning exact-reconstruction labels.

## Sources That Do Not Yet Supply The Needed Answer

[CADGenBench](https://github.com/huggingface/cadgenbench) keeps evaluation GT
private. Public inputs and a validity checker are useful evaluation material,
but cannot supply our requested local per-example ground-truth answers alone.

No source in this screening has yet been verified to supply the complete
AutoCAD observation/action/recovery trace needed for the budget-and-recovery
direction. Our existing audited executions are the directly available evidence.
Likewise, missing-dimension clarification needs paired incomplete/complete input
or expert answers; the presence of a STEP file alone does not label the best
question to ask a human.

## Next Sample-Level Check

Inspect candidate parts for the six observed directions before expanding counts:
identifiable asymmetric views; exact engineered features; controlled local edits;
same-silhouette/different-volume alternatives; staged execution and recovery;
and meaningful missing-dimension clarifications. For every retained sample,
require an actual input artifact, a natural request, an available answer, and
evidence supporting that answer. Keep model output, expert target and synthetic
derivative distinct. No training or benchmark split was changed in this pass.
