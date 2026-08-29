# CAD Agent Evaluation Architecture

## Boundaries

The demo separates three kinds of state:

1. **Source**: the AutoCAD skill, MCP bridge, verifier, schemas, and runner code. Git owns their long-term history.
2. **Evaluation definitions**: selected task descriptions, rubrics, metadata, and the pinned upstream dataset revision.
3. **Run records**: agent actions, attempts, CAD artifacts, extracted scenes, and verdicts. The run ledger owns these immutable records.

Source snapshots inside a run complement Git; they do not replace it. A run records the Git commit and dirty state when available, and always copies the exact source files used with SHA-256 hashes.

## Storage

```text
records/
  run-index.sqlite3             # Rebuildable query index
  mcp-audit.jsonl               # Raw MCP audit stream
  <sample-id>/<run-id>/
    run.json                    # Run, source, input, attempt, result manifest
    trajectory.jsonl            # Append-only observable events
    source/                     # Exact skill/MCP/verifier snapshots
    inputs/                     # Exact task inputs used by the run
    attempts/a001/...           # Immutable scripts, DWGs, logs, scenes, verdicts
```

`run.json` and `trajectory.jsonl` are the facts. SQLite is only an index and can be regenerated with `reindex`.

## Lifecycle

```powershell
python scripts/run_ledger.py reuse --sample-id <sample-id>
python scripts/run_ledger.py start --sample-id <sample-id>
python scripts/run_ledger.py attempt --run <run-id> --label initial
python scripts/run_ledger.py artifact --run <run-id> --attempt a001 --role candidate --path candidate.dwg
python scripts/run_ledger.py event --run <run-id> --attempt a001 --type decision --summary "Disabled OSNAP for deterministic dimensions"
python scripts/run_ledger.py ingest-mcp --run <run-id>
python scripts/run_ledger.py finish --run <run-id> --attempt a001 --verdict verdict.json
python scripts/run_ledger.py verify-integrity --run <run-id>
python scripts/run_ledger.py diff --from-run <old-run> --to-run <new-run>
```

Create a new attempt for a CAD repair. Create a child run when the task input, skill, MCP, verifier, model, or orchestration policy changes materially. Never overwrite recorded artifacts.

## Trajectory Policy

Record observable execution facts: tool calls, command inputs, exit states, artifacts, verifier evidence, failures, retries, and short decision summaries. Do not store private chain-of-thought, credentials, ambient chat, or unrelated filesystem contents. Secret-like fields are redacted before persistence.

## Reuse

`reuse` selects the highest-scoring passed run, verifies the artifact hash, and returns or copies the requested artifact. Reuse is allowed only when the sample input and relevant source policy still match. A future cache policy should make this automatic by comparing input and source digests.

## Controlled System Improvement

Two improvement modes share the same immutable evaluation boundary:

1. **Online adaptive development** gives a supervisor the complete typed
   diagnostic envelope and lets it choose a drawing repair, subsystem retry, or
   authorized candidate-system patch. A separate modifier edits only the named
   files in `improvement/adaptive/<session>/workspace`. Each accepted version has
   before/after hashes and must pass component validation; failed candidates are
   rolled back. Iteration, wall-clock, and stagnation limits are safety budgets,
   not a hard-coded repair workflow.
2. **Offline A/B evaluation** freezes production and candidate profiles, then
   compares them without source-edit permission. It is the confirmation and
   promotion gate, not the mechanism by which the online agent learns.

The diagnostic envelope preserves process return codes, timeouts, exception type
and traceback tail, full verifier output, completed and failed checks, MCP tool
errors, and artifact identities. This allows the supervisor to distinguish a bad
drawing from a broken verifier or interface. Production source, samples, rubrics,
records, historical trajectories, and the fixed holdout split are not writable
inputs to either improvement agent.

The 50 samples are pinned to 40 development and 10 holdout samples in
`improvement/split.json`. Improvement evidence contains development runs only.
A proposal may contain candidate copies of prompt, skill, MCP, and verifier
files, each with before/after SHA-256 hashes. Batch runs load these copies with
`--proposal` without promoting them.

Long evaluations run through `scripts/run_ab.py`. Its durable status file records
the active phase, child PID, result counts, timestamps, and phase logs. A resumed
batch skips only stable results; orphaned working directories and transient
failures are retained and retried in numbered directories so failure evidence is
not destroyed.

Promotion requires matching production and candidate reports across all 50
samples, passing tests and artifact integrity, no average score/coverage/pass-rate
regression, and no sample regression beyond the configured tolerance. Verifier
changes additionally require independent approval. A promoted release stores
both the previous and promoted source and supports explicit rollback.

## Production Gaps

- Capture Codex SDK run and agent IDs when execution moves into a programmatic runner.
- Ingest context-tagged MCP audit events into each run automatically.
- Calibrate VLM confidence against a labeled holdout and report accuracy by rubric family; the current 0.85 threshold is a conservative policy, not a measured guarantee.
- Add topology-specific deterministic checks so visual evidence is not used where geometry can be proven directly.
- Store large binary artifacts in object storage while retaining content hashes and URIs in the manifest.
- Add schema migration, retention, access control, and PII deletion policies before multi-user use.
