# Query/Input/Reward Taxonomy

Date: 2026-09-16. Scope: EvoCAD post-training and evaluation planning.

This document reorganizes the current dataset-family registry into the three
training/evaluation buckets we want to expose to the agent: Text, QueryCAD
(Code), and Assembly (image-text). It intentionally separates accepted local
artifacts from candidate external datasets.

## 1. Text

Text covers tasks where the final answer is symbolic or numeric, not a CAD file.
The model may see images, but it submits structured text/JSON.

### T1: Real Engineering Drawing QA

- Query: short question or structured question about a real mechanical drawing.
- Input: full drawing image, optional boxed ROI or crops.
- Output: JSON answer: line role, dimension value, dimension-chain result,
  section solid/void, cross-view relation, or sufficiency judgement.
- Reward/metric:
  - exact string/boolean match;
  - numeric absolute tolerance, usually <= 0.1 mm;
  - accepted aliases only if frozen before the run;
  - timeout/no submission is a process failure.
- Physical quantities:
  - nominal dimension in mm;
  - line role class;
  - derived dimension-chain result;
  - sufficient/insufficient evidence flag.
- Dataset/source used:
  - user-supplied drawing PDF pages;
  - public xifeng drawing previews.
- Local artifacts:
  - `evals/data/posttrain/real-drawings/source-r2/sources.json`;
  - `evals/data/posttrain/real-drawings/tasks-r1/pilot-summary.json`.
- GT status: model-proposed pending human review.

### T2: Synthetic CAD-VQA From Verified BRep

- Query: perception, dimension, projection, or sufficiency question.
- Input: generated drawing/renders from known STEP/BRep.
- Output: JSON answer.
- Reward/metric:
  - same JSON field checks as T1;
  - answer bound to private BRep-derived GT;
  - negative controls must fail.
- Physical quantities:
  - bounding dimensions in mm;
  - bore diameter/depth;
  - view direction;
  - visible/hidden/dimension/extension line role.
- Dataset/source used:
  - Autodesk Fusion 360 Gallery reconstruction r1.0.1.
- Local artifacts:
  - `evals/data/posttrain/pilot-r4/pilot-summary.json`;
  - `evals/data/sources/fusion360gallery/posttrain-fusion-r1/source-manifest.json`.
- GT status: verified GT.

## 2. QueryCAD (Code)

QueryCAD covers tasks where the model produces code, API calls, or a CAD artifact.
This is where most actual RL/environment work will live.

### C1: Orthographic Views To BRep

- Query: build the part from three views and dimensions.
- Input: front/top/right views plus dimension/specification sheet.
- Output: one STEP solid in the stated fixed coordinate frame.
- Reward/metric:
  - candidate STEP imports as a valid solid;
  - fixed-frame bbox/extent checks;
  - missing material volume;
  - extra material volume;
  - no auto mirror/translation alignment;
  - realistic negative controls rejected.
- Physical quantities:
  - volume mm^3;
  - bbox extents mm;
  - missing/extra BRep volume mm^3;
  - feature diameter/depth/location;
  - topology sanity checks where available.
- Dataset/source used:
  - Fusion generated reconstruction fixtures;
  - OmniMech-style local benchmark evidence.
- Local artifacts:
  - `evals/data/posttrain/pilot-r4/tasks/reconstruct-01`;
  - `evals/data/posttrain/pilot-r4/tasks/reconstruct-02`;
  - `evals/geometry-benchmarks/reference-runs/geometry-smoke-v2.json`.
- GT status: verified GT.

### C2: Text/Image To CadQuery

- Query: natural-language CAD prompt or prompt plus render/image.
- Input: text, optional single-view/multi-view render.
- Output: executable CadQuery Python script and exported STEP/STL.
- Reward/metric:
  - script executes in pinned sandbox;
  - exported CAD imports successfully;
  - target/candidate Chamfer distance if meshable;
  - BRep missing/extra volume where a target BRep exists;
  - syntax/API/runtime failures penalized separately.
- Physical quantities:
  - Chamfer distance;
  - volume error;
  - bbox error;
  - feature count/type agreement;
  - valid solid count.
- Dataset/source used:
  - IterCAD_Data candidate;
  - Text-to-CadQuery lineage candidate;
  - local `cad-1000-hours` adaptive/verifier skeleton.
- Local artifacts:
  - `evals/cad-1000-hours`.
- GT status: candidate GT not imported.

### C3: CAD API / AutoCAD Action Generation

- Query: CAD task text, possibly with drawing/screenshot/current CAD state.
- Input: natural language, drawing image, current file state, CAD backend choice.
- Output: AutoCAD MCP calls, AutoLISP, COM-style action trace, or generated CAD file.
- Reward/metric:
  - tool/API call succeeds;
  - CAD worker returns stable receipt;
  - output opens/imports;
  - topology export matches expected structure;
  - BRep/geometry comparison passes;
  - watchdog restart/hang is counted as operational failure.
- Physical quantities:
  - same BRep metrics as C1;
  - entity counts/layers when relevant;
  - native CAD topology summary;
  - execution time and crash/hang state.
- Dataset/source used:
  - local audited AutoCAD MCP jobs;
  - ComAct/ComCADBench concept as external candidate.
- Local artifacts:
  - `mcp/autocad_mcp_audited.py`;
  - `mcp/autocad_core_console.py`.
- GT status: no accepted GT yet.

### C4: Verifier-Feedback Repair Loop

- Query: repair instruction with verifier feedback and trajectory history.
- Input: initial wrong CAD artifact, public drawing/spec, previous attempts,
  verifier localization, and action history.
- Output: corrected artifact plus structured reflection/action decision.
- Reward/metric:
  - final artifact passes the underlying task verifier;
  - improvement over previous attempt;
  - process reward for using verifier feedback;
  - penalties for repeated observation/action loops without submission;
  - no private GT access.
- Physical quantities:
  - delta missing/extra volume;
  - delta bbox/feature error;
  - number of iterations;
  - observation count before commit;
  - recovered feature IDs if available.
- Dataset/source used:
  - local Fusion repair tasks;
  - CAD-1000-hours adaptive skeleton.
- Local artifacts:
  - `evals/data/posttrain/pilot-r4/tasks/repair-01`;
  - `evals/cad-1000-hours/adaptive/session.py`.
- GT status: verified GT for local repair fixtures.

### C5: CAD-CAE Long-Horizon

- Query: engineering paper/specification task.
- Input: paper figures, text, CAD requirements, mesh/simulation targets.
- Output: CAD geometry, mesh/solver setup, logs, post-processing report.
- Reward/metric:
  - stage-wise CAD geometry checks;
  - mesh quality checks;
  - solver/log completion;
  - post-processing quantity consistency;
  - report/source citation consistency.
- Physical quantities:
  - geometry dimensions;
  - mesh cell count, skewness, y+ where applicable;
  - solver residuals/convergence;
  - target engineering quantities from the case.
- Dataset/source used:
  - local film-cooling paper tasks;
  - SimLoop direction referenced by IndustryForge.
- Local artifacts:
  - `evals/Paper_filmcooling/runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/result.json`;
  - `evals/Paper_filmcooling/runs/thole-baseline-hole-astra-ultra-20260915/attempts/a001/geometry-report.json`.
- GT status: candidate GT not imported.

## 3. Assembly (Image-Text)

Assembly covers multi-part CAD where the target is not just a single solid, but
a component graph plus spatial/mating constraints.

### A1: Assembly Specification To CAD Assembly

- Query: assembly requirement or structured component/interface specification.
- Input: natural language, part images/renders, component files, interface
  descriptions, exploded views, or assembly drawing.
- Output: parametric parts, assembly script, transforms/mates, and assembled CAD.
- Reward/metric:
  - all required components present;
  - each part passes part-level BRep checks;
  - transforms/mates satisfy the interface graph;
  - collision/interference below threshold;
  - degrees of freedom and constraints match the specification;
  - BOM/component identity agreement.
- Physical quantities:
  - transform matrices;
  - mate/axis/plane distance and angle residuals;
  - interference volume;
  - clearance distances;
  - part count and graph connectivity.
- Dataset/source used:
  - Autodesk Fusion 360 Gallery Assembly dataset;
  - AssemCAD candidate.
- Local artifacts:
  - `evals/posttrain/cad_data_families.json` currently only records this as a
    planned import family.
- GT status: candidate GT not imported.

## Reward Naming

The current project mostly has acceptance verifiers, not a deployed RL reward.
When we say reward going forward, use these names:

- `R_json`: JSON/text answer correctness.
- `R_exec`: code or CAD API execution success.
- `R_geom`: BRep/mesh geometry agreement.
- `R_feature`: named feature-level agreement.
- `R_assembly`: mate/component/interference correctness.
- `R_process`: observation budget, submission, reflection, and use of feedback.
- `R_safety`: no GT leakage, no verifier tampering, no tool-boundary violation.

Final task reward should be a typed vector first, then a scalar only for a
specific training run. The scalar should not hide whether failure came from
perception, code execution, geometry, assembly constraints, or process control.
