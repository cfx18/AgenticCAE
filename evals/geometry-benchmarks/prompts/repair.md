You are repairing EvoCAD geometry sample $sample_id after deterministic geometry feedback.

Work only from task.json, input_files, the previous best drawing at $previous_candidate, its sanitized verifier result at $verdict, and the most recent attempted repair result at $latest_verdict. Do not inspect parent directories, dataset manifests, ground-truth CAD files, or other evaluation records. When the two verdict paths differ, start from the best drawing but use the latest verdict to avoid repeating a regression.

Read and follow the AutoCAD skill at $skill_path.

First call autocad_set_run_context with sample_id=$sample_id, run_id=$run_id, and attempt_id=$attempt_id. Read the full verifier result. The global metrics describe overlap, surface distance, extents, volume, and watertightness; mismatch positions are normalized within the ground-truth bounding box. Treat them as measurement feedback, not permission to weaken the verifier.

AutoCAD Core Console does not provide the desktop application ActiveX object. Do not call `vlax-get-acad-object`, `vla-get-ActiveDocument`, or desktop document APIs. Use entity functions, selection sets, direct commands, and DXF data instead.

Before editing, write JSON to $reflection with keys failure_owner, observed_failures, root_causes, planned_geometry_changes, and confidence. failure_owner must be drawing, task, mcp, verifier, or harness. Then repair the previous drawing with isolated autocad_core_start jobs using input_path=$previous_candidate and output_path=$candidate. Preserve correct features and change only geometry supported by the reference drawing and verifier evidence. The final output must contain one native editable 3DSOLID and no annotations.

Finish only after autocad_core_status reports succeeded. Do not modify prompts, skills, MCP code, verifier code, manifests, or prior artifacts during this repair turn.
