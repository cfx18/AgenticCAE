You are closing the feedback loop for EvoCAD geometry attempt $attempt_id on sample $sample_id.

This is the same agent trajectory that produced the candidate. The harness has now evaluated that exact candidate. Analyze the current result before any next modeling turn. Do not edit CAD, prompts, skills, MCP code, verifier code, manifests, or prior artifacts in this turn.

Current sanitized verifier result:

$verdict_json

Trajectory state:

- iteration: $iteration
- current score: $current_score
- best score so far, including this candidate when scorable: $best_score
- consecutive non-improving iterations: $non_improving
- elapsed job time: $elapsed_seconds seconds
- remaining job time: $remaining_seconds seconds
- candidate DWG exists: $candidate_exists
- verifier-ready candidate mesh exists: $mesh_exists
- action process timed out: $action_timed_out
- action return code: $action_return_code

Current-turn diagnostics from the harness and audited MCP boundary:

$diagnostics_json

Decide whether another evidence-grounded geometry iteration is worthwhile. Inspect the relationship between the drawing, current structure, verifier metrics, localized mismatch regions, and tool, MCP, backend, export, or artifact failures visible in the feedback packet. Use localized regions to state where a repair should occur. When present, `candidate_topology_faces` ranks nearby native AutoCAD faces, `engineering_feature_candidates` gives conservative analytic-surface interpretations, `boolean_lineage` distinguishes inherited faces from faces created or modified by the latest job, and `responsible_operation_candidates` links those faces to parameter-bearing Agent-declared operations. Prefer a high-confidence face-lineage link over a shared final entity handle. Multiple operations in one Core Console job remain an operation group rather than exact causality. These are diagnostic evidence with explicit confidence, not guaranteed recovery of design intent; confirm them against the drawing rather than inventing unsupported feature semantics. A transport-level `pass` only means the MCP call completed; compare its nested backend result with the verifier outcome. A recoverable regression such as NO_SOLIDS, an export failure, or a broken Boolean result is normally a reason to continue from the previous best checkpoint, not a reason to stop. Do not propose weakening thresholds or using evaluator-only ground-truth files.

Return `continue` only when you can name concrete, reference-consistent changes or a concrete recovery action with a plausible score gain. Return `stop` when strict passage is achieved, the visible input is genuinely insufficient, the blocker is not recoverable through another CAD turn, or no defensible structural improvement remains. `max_iterations` is enforced outside this decision and must not be treated as your reasoning limit.

Your response must match the supplied JSON schema. `planned_geometry_changes` becomes the plan for the next modeling turn. Keep failure attribution factual; use `none` after a valid strict pass. When evidence points to a shared prompt, skill, MCP, verifier, harness, or task defect, record a concise `system_change_proposal`; the fixed evaluation runner will version and evaluate that proposal separately rather than mutating the shared system inside this sample.
