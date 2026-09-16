# EvoCAD Post-Training Data Families

Date: 2026-09-16. Scope: noncommercial research. This is a registry and
integration plan, not a claim that all listed sources are accepted training data.

## Why This Split

IndustryForge-27B is useful to us because it separates CAD capability into
foundation-model skills instead of treating every task as "image to CAD". Its
reported SFT mix is CAD-VQA, Text-to-CadQuery, COM CAD, and CadQuery Assembly.
For EvoCAD we keep the same separation, then add repair/reflection and CAD-CAE
long-horizon tasks because those are where our agent loop becomes interesting.

The machine-readable version is `evals/posttrain/cad_data_families.json`.
Validation code is in `src/cad_evoloop/posttrain/dataset_families.py`.

## Current Families

1. `cad_vqa_real_drawing`: real mechanical drawing QA. We have 20 model-proposed
   tasks under `evals/data/posttrain/real-drawings/tasks-r1`, 18 diagnostic-eligible,
   and zero human-accepted labels. This is good for Kimi bad-pattern discovery,
   but not SFT gold yet.
2. `cad_vqa_synthetic_from_gt_brep`: generated drawing QA from Fusion BRep. We
   have 20 mechanically checked tasks in `evals/data/posttrain/pilot-r4` and 32
   bounded Fusion source parts. This is the cleanest verified-GT seed.
3. `orthographic_to_brep`: three-view/specification to STEP. We have two
   controlled reconstruction fixtures, prior OmniMech-style geometry evidence,
   and 20 ready-to-use seed tasks in `evals/data/posttrain/multifamily-seed-r1`.
   Kimi has not been run here because the current smoke harness does not safely
   execute model-generated CAD code.
4. `text_or_image_to_cadquery`: IterCAD/Text-to-CadQuery style program synthesis.
   We now have 20 deterministic seed tasks in `evals/data/posttrain/multifamily-seed-r1`.
   The future importer should still preserve prompt, render, solution code,
   target geometry, execution receipt, and train/test leakage hashes for external
   datasets.
5. `cad_api_action`: AutoCAD/COM/MCP action generation. We already have audited
   AutoCAD MCP surfaces and 20 deterministic CAD-action fixture tasks. These are
   not live AutoCAD/SolidWorks sessions; real software sessions still need
   watchdog and restart hardening before batch model runs.
6. `assembly_spec_to_cad`: assembly specification to parts/mates. This is
   seeded with 20 component-spec tasks in `evals/data/posttrain/multifamily-seed-r1`.
   They include component reference JSON but are graded by final BRep until a
   multi-body/mate verifier is added.
7. `repair_reflection_loop`: defective CAD plus verifier feedback to corrected
   artifact. We have local repair fixtures and adaptive-loop code, but this
   needs richer verifier localization before it becomes a reward dataset.
8. `cad_cae_long_horizon`: CAD to mesh/simulation/post-processing. We have
   film-cooling case-study runs; these stay separate from short CAD SFT because
   their labels are stage-wise and expensive.

## Kimi Status

Existing Kimi smoke, reused rather than rerun:

- Fusion/generated drawing perception: `.local/posttrain/kimi-smoke-r3/summary.json`.
  Historical r3 attempted 14, graded 13, passed 13, timeout 1. Follow-up
  `.local/posttrain/kimi-smoke-missing-r1/summary.json` added `line-01` and
  retried `projection-01`; both passed. Latest successful coverage is 15/15
  Kimi-testable perception tasks.
- Real drawing QA: `evals/data/posttrain/real-drawings/kimi-r1/summary.json`.
  Historical r1 now contains 18 diagnostic-eligible attempts, with one earlier
  timeout on `drawing-02`. Follow-up
  `evals/data/posttrain/real-drawings/kimi-missing-r1/summary.json` retried
  `drawing-02`, which passed after 415 seconds. Latest successful coverage is
  18/18 diagnostic-eligible tasks. These scores mean agreement with
  model-proposed labels, not expert-GT accuracy.

## Multi-Family Seed R1

`evals/posttrain/build_multifamily_seed.py` created
`evals/data/posttrain/multifamily-seed-r1` with 120 ready-to-use sealed tasks:

- 20 `drawing_qa`
- 20 `orthographic_to_brep`
- 20 `cad_repair_edit`
- 20 `text_image_to_cad_program`
- 20 `cad_software_operation`
- 20 `assembly`

All 120 trusted reference outputs pass the existing verifier. The CAD software
operation family is a deterministic action fixture, not live CAD automation. The
assembly family records component GT but currently scores final fused BRep.

## Next Implementation Steps

1. Add one importer per planned source, but make every importer produce the same
   posttrain bundle shape: `public/`, `private/`, `reference/`, `tests/`,
   `provenance/`, and sealed `manifest.json`.
2. Keep three label tiers explicit: verified GT, model-proposed pending human,
   and candidate source not imported.
3. Extend the Kimi harness into two separate modes: perception-only JSON and
   sandboxed code/STEP production. Do not run geometry-making tasks in the
   perception-only harness.
4. Build the next 20-30 sample batch only from families with a verifier that can
   reject at least one realistic negative control.
