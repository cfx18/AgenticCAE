# Codex VLM verifier

This package resolves rubric checks that the deterministic AutoCAD scene
verifier explicitly marks `unverified`. It does not replace geometry checks.

## Interface

`CodexCliProvider.evaluate(prompt, images, schema_path, work_dir, expected_ids)`
is the provider boundary. It invokes the locally authenticated `codex exec`
binary with:

- one or more candidate images followed by reference images;
- a strict JSON output schema;
- an ephemeral, read-only session;
- user config and project rules disabled;
- MCP servers replaced with an empty table;
- JSONL events and stderr retained for audit.

The provider rejects non-zero exits, unexpected or duplicate rubric IDs,
malformed evidence regions, and any emitted command, computer, file-search,
MCP, or web-search tool item.

`CAD_VLM_MODEL` selects the model; the default is `gpt-5.5`. A different
provider can implement the same return pair: `(visual_result, metadata)`.

## Decision policy

Only deterministic rubric entries whose status is `unverified` are sent to the
VLM. A high-confidence first evaluation resolves the rubric immediately. When
any target remains below that threshold, production runners request two more
isolated evaluations. A repeated result resolves a rubric only when at least
two thirds of all evaluations agree, each counted vote has confidence at least
0.65, and the agreeing votes average at least 0.70. Conflicts remain incomplete.
The merge order is:

1. Any deterministic failure makes the combined decision `fail`.
2. Any accepted visual failure makes it `fail`.
3. Any unresolved target makes it `incomplete`.
4. Otherwise it is `pass`.

The output preserves every raw evaluation, the consensus calculation,
accepted/unresolved lists, normalized evidence boxes, prompt/model metadata,
image SHA-256 hashes, deterministic score, and coverage before and after visual
evaluation.

## Rendering and ledger

Render an extracted scene without opening AutoCAD:

```powershell
python -m verifier.vlm.render_scene `
  --scene runs/<workflow-id>/scene.json `
  --output runs/<workflow-id>/candidate.png
```

Pass both `--ledger-run` and `--attempt` to `verifier.vlm.evaluate` to copy the
verdict and append a `vlm.completed` event. Finish the run with the same verdict
to persist its top-level pass, score, and combined coverage.
