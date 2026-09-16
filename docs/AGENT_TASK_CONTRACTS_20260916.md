# EvoCAD Agent Task Contracts

Date: 2026-09-16. This summarizes the task types an agent can touch in the
current project: query, input, output, environment, reward/physical quantities,
and dataset source.

## 1. Drawing QA: Real Engineering Drawings

- Representative datasets:
  - local/user-supplied engineering drawing PDF pages, landed under
    `evals/data/posttrain/real-drawings/source-r2`;
  - xifengboke public drawing previews, discovered from public articles;
  - IndustryForge category analogue: CAD-VQA.
- Query: short or structured question about line type, dimension attachment,
  dimension-chain calculation, section solid/void, cross-view mapping, or
  whether enough information is available.
- Input visible to agent:
  - full drawing image;
  - optional boxed ROI or crop;
  - public `task.json` with answer format.
- Output expected:
  - `answer.json`, usually `{"answer": ...}` or structured fields.
- Environment:
  - posttrain `Episode`;
  - perception-only MCP tools: `observe`, `conclude`, `submit`;
  - no CAD execution, shell, web, or private GT access.
- Reward / physical quantities:
  - exact categorical/text match;
  - numeric absolute tolerance, typically <= 0.1 mm;
  - frozen aliases for boxed text answers;
  - process failure for timeout/no submit;
  - quantities: nominal mm values, line-role class, dimension-chain result,
    solid/void label, sufficiency flag.
- Dataset:
  - user-supplied engineering drawing PDF pages;
  - public xifeng preview drawings.
- Current local data:
  - `evals/data/posttrain/real-drawings/tasks-r1`;
  - 20 proposed tasks, 18 diagnostic-eligible, zero human-accepted GT.

## 2. Drawing QA: Synthetic Drawings From Verified BRep

- Representative datasets:
  - Autodesk Fusion 360 Gallery reconstruction r1.0.1, landed under
    `evals/data/sources/fusion360gallery/posttrain-fusion-r1`;
  - local generated pilot bundle `evals/data/posttrain/pilot-r4`;
  - IndustryForge category analogue: CAD-VQA generated from CAD source.
- Query: perception, dimension, projection diagnosis, cross-view size, or
  clarification question.
- Input visible to agent:
  - generated orthographic images;
  - sometimes generated dimension/spec image;
  - public `task.json`.
- Output expected:
  - `answer.json` with requested fields.
- Environment:
  - posttrain `Episode`;
  - perception-only MCP tools: `observe`, `conclude`, `submit`;
  - no CAD execution for this smoke harness.
- Reward / physical quantities:
  - JSON field correctness;
  - numeric tolerances from BRep-derived GT;
  - negative controls must be rejected by verifier;
  - quantities: bbox extents in mm, bore diameter/depth, projected view
    direction, line-role class, sufficiency flag.
- Dataset:
  - Autodesk Fusion 360 Gallery reconstruction r1.0.1.
- Current local data:
  - `evals/data/posttrain/pilot-r4`;
  - `evals/data/sources/fusion360gallery/posttrain-fusion-r1`;
  - 20 mechanically checked tasks from 32 bounded source parts.

## 3. Three-View / Spec To 3D BRep

- Representative datasets:
  - local Fusion reconstruction fixtures in `evals/data/posttrain/pilot-r4/tasks/reconstruct-*`;
  - OmniMech-style local benchmark records under `evals/geometry-benchmarks`;
  - future better external target: datasets with paired orthographic drawings
    and STEP/BRep GT.
- Query: build the part from three orthographic views and complete dimensions.
- Input visible to agent:
  - front/top/right drawing images;
  - manufacturing dimension/spec sheet;
  - public coordinate convention and answer filename.
- Output expected:
  - `model.step`, one valid solid in the fixed coordinate frame.
- Environment:
  - posttrain bundle layout exists;
  - safe model-code execution environment is not yet enabled for Kimi;
  - reference solutions are trusted fixtures, not learner runs.
- Reward / physical quantities:
  - STEP imports and is a valid solid;
  - fixed-frame bbox/length checks;
  - missing material volume;
  - extra material volume;
  - no automatic translation, rotation, or mirror alignment;
  - negative STEP controls must fail;
  - quantities: volume mm^3, bbox extents mm, missing/extra BRep volume mm^3,
    feature diameter/depth/location.
- Dataset:
  - Fusion generated reconstruction fixtures;
  - OmniMech-style local benchmark evidence.
- Current local data:
  - `evals/data/posttrain/pilot-r4/tasks/reconstruct-01`;
  - `evals/data/posttrain/pilot-r4/tasks/reconstruct-02`;
  - `evals/geometry-benchmarks/reference-runs/geometry-smoke-v2.json`.

## 4. Local CAD Repair

- Representative datasets:
  - local Fusion repair fixtures in `evals/data/posttrain/pilot-r4/tasks/repair-*`;
  - CAD-1000-hours adaptive skeleton under `evals/cad-1000-hours`;
  - future external analogue: CAD edit / repair trajectory datasets with
    initial artifact, target artifact, and verifier-readable deltas.
- Query: repair an initial wrong CAD file to satisfy the drawing/specification.
- Input visible to agent:
  - `initial.step`;
  - drawing/specification images;
  - public task description;
  - in adaptive variants, verifier feedback and trajectory history.
- Output expected:
  - corrected `model.step`;
  - for loop variants, structured reflection/action decision.
- Environment:
  - posttrain bundle plus adaptive-loop/run-ledger skeleton;
  - code/CAD execution sandbox still needs hardening before broad Kimi runs.
- Reward / physical quantities:
  - same final BRep verifier as reconstruction;
  - improvement over previous attempt;
  - process reward for using verifier feedback;
  - penalties for repeated observe/act loops without submission;
  - quantities: delta missing/extra volume, delta bbox error, feature error,
    iteration count, observation count.
- Dataset:
  - Fusion repair fixtures;
  - CAD-1000-hours adaptive skeleton.
- Current local data:
  - `evals/data/posttrain/pilot-r4/tasks/repair-*`;
  - `evals/cad-1000-hours/adaptive/session.py`.

## 5. Text/Image To CadQuery Program

- Representative datasets:
  - IterCAD_Data on Hugging Face, candidate not imported;
  - Text-to-CadQuery lineage, candidate not imported;
  - local `evals/cad-1000-hours` as environment/verifier skeleton, not accepted
    Text-to-CadQuery data;
  - IndustryForge category analogue: text2cadquery and image/text-to-CadQuery.
- Query: natural-language CAD build request, sometimes with render/image.
- Input visible to agent:
  - prompt text;
  - optional image/render;
  - expected output contract for CadQuery script.
- Output expected:
  - executable CadQuery Python;
  - exported STEP/STL.
- Environment:
  - planned posttrain code-production environment;
  - CadQuery pinned environment required;
  - not currently part of Kimi perception smoke.
- Reward / physical quantities:
  - script parses and executes;
  - artifact imports successfully;
  - target/candidate Chamfer distance if mesh comparison is available;
  - BRep missing/extra volume where target BRep exists;
  - bbox error, volume error, feature count/type agreement.
- Dataset:
  - IterCAD_Data candidate;
  - Text-to-CadQuery candidate;
  - local `cad-1000-hours` skeleton as environment substrate.
- Current local data:
  - no accepted imported 20-30 sample set yet.

## 6. AutoCAD / CAD API Action Task

- Representative datasets:
  - local AutoCAD MCP/audited job records from `mcp/`;
  - ComAct / ComCADBench, candidate external source;
  - IndustryForge category analogue: COM CAD tasks (`com_2d`, `com_3d`,
    `com_assembly`).
- Query: CAD software operation task.
- Input visible to agent:
  - natural-language instruction;
  - optional drawing/screenshot;
  - current CAD/backend state;
  - MCP/API tool descriptions.
- Output expected:
  - AutoCAD MCP calls, AutoLISP, COM-style trace, or generated CAD file.
- Environment:
  - local AutoCAD MCP/audited job surface;
  - AutoCAD Core Console fallback;
  - needs watchdog/restart cleanup to avoid manual intervention.
- Reward / physical quantities:
  - API/tool call succeeds with receipt;
  - output opens/imports;
  - topology export passes structural checks;
  - BRep geometry matches target where available;
  - hang/crash/restart state is part of process score;
  - quantities: entity counts, layer/type counts, topology summary, BRep
    missing/extra volume, execution time.
- Dataset:
  - local AutoCAD MCP runs;
  - ComAct/ComCADBench as candidate external source.
- Current local data:
  - `mcp/autocad_mcp_audited.py`;
  - `mcp/autocad_core_console.py`;
  - no accepted GT batch yet.

## 7. Assembly Specification To CAD Assembly

- Representative datasets:
  - Autodesk Fusion 360 Gallery Assembly dataset, candidate not imported;
  - AssemCAD candidate;
  - IndustryForge category analogue: CadQuery Assembly and COM assembly tasks.
- Query: assemble parts according to textual/graphical constraints.
- Input visible to agent:
  - component files or generated parts;
  - natural-language assembly spec;
  - possible exploded view or assembly drawing;
  - interface/mate constraints.
- Output expected:
  - parts, transforms, mates/constraints, assembled CAD artifact.
- Environment:
  - planned assembly importer/verifier;
  - not yet runnable as a learner task in this project.
- Reward / physical quantities:
  - all required components present;
  - part-level BRep checks pass;
  - mate/axis/plane constraints satisfied;
  - unacceptable interference absent;
  - BOM/component graph matches;
  - quantities: transform matrices, mate residuals, angle/distance residuals,
    interference volume, clearance distances, graph connectivity.
- Dataset:
  - Autodesk Fusion 360 Gallery Assembly dataset;
  - AssemCAD candidate.
- Current local data:
  - registry entry only; no imported 20-30 sample set yet.

## 8. CAD-CAE Long-Horizon Task

- Representative datasets:
  - local film-cooling paper tasks under `evals/Paper_filmcooling`;
  - SimLoop direction referenced by IndustryForge, direction reference rather
    than imported dataset;
  - future target: paper/spec-to-CAD/mesh/simulation trajectory datasets.
- Query: reproduce or analyze engineering geometry from paper/specification and
  proceed through CAD, mesh, simulation setup, and post-processing.
- Input visible to agent:
  - paper PDF pages/figures;
  - extracted text;
  - geometry requirements;
  - mesh/simulation target requirements.
- Output expected:
  - CAD geometry;
  - mesh/solver setup;
  - logs and post-processing report.
- Environment:
  - local paper-case harnesses;
  - AutoCAD/CAE toolchain experiments;
  - expensive case-study mode, not standard 20-30 batch yet.
- Reward / physical quantities:
  - geometry stage checks;
  - mesh quality checks;
  - solver/log completion;
  - post-processing quantity consistency;
  - source/report consistency;
  - quantities: geometry dimensions, mesh cell count, skewness, y+, residuals,
    target engineering coefficients or fields.
- Dataset:
  - local film-cooling paper tasks;
  - SimLoop direction referenced by IndustryForge.
- Current local data:
  - `evals/Paper_filmcooling/runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/result.json`;
  - `evals/Paper_filmcooling/runs/thole-baseline-hole-astra-ultra-20260915/attempts/a001/geometry-report.json`.

## Shared Reward Vector

The current implementation mostly uses verifiers/acceptance checks. A true RL
reward should stay vector-valued until a training run chooses weights:

- `R_json`: symbolic/numeric answer correctness.
- `R_exec`: code/API execution success.
- `R_geom`: BRep or mesh geometry agreement.
- `R_feature`: named feature-level agreement.
- `R_assembly`: components, mates, constraints, interference, graph.
- `R_process`: observation budget, timely submit, reflection, use of feedback.
- `R_safety`: no private GT access, verifier tampering, or tool-boundary breach.
