You are continuing EvoCAD geometry sample $sample_id after a verified CAD attempt.

Work only from task.json, the reconstruction IR embedded below, the previous best drawing at $previous_candidate, its verifier result at $verdict, the latest result at $latest_verdict, and the decision at $reflection. Follow the IR condition-specific evidence policy. Do not inspect input images unless the policy explicitly permits them. Do not inspect parent directories, manifests, ground-truth files, or other runs.

Read and follow the AutoCAD skill at $skill_path. First call autocad_set_run_context with sample_id=$sample_id, run_id=$run_id, and attempt_id=$attempt_id.

Use verifier mismatch localization to identify the smallest IR feature or assumption that explains the error. Update the construction hypothesis explicitly in your reasoning, then repair the previous best drawing with isolated autocad_core_start jobs using input_path=$previous_candidate and output_path=$candidate. The IR is not a command whitelist: any supported AutoCAD geometry operation is allowed. Preserve correct features and do not weaken the verifier.

Attach an operation_manifest to each job with stable operation IDs, unrestricted operation_type, feature_id, parameters, and parent_operation_ids. Use topology and Boolean lineage evidence when available. This metadata is provenance only.

AutoCAD Core Console does not provide the desktop application ActiveX object. Do not call vlax-get-acad-object, vla-get-ActiveDocument, or desktop document APIs. The final output must contain one native editable 3DSOLID and no annotations.

Finish only after autocad_core_status reports succeeded. Do not modify prompts, skills, MCP code, verifier code, manifests, the reconstruction IR, or prior artifacts during this turn.
