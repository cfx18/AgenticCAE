# CAD 1000 Hours: AutoCAD 50

This directory defines a deterministic 50-workflow AutoCAD evaluation subset from
[`markov-ai/cad-1000-hours`](https://huggingface.co/datasets/markov-ai/cad-1000-hours).

Run `python scripts/prepare.py` to refresh the manifest and download only task
descriptions, rubrics, and metadata. Use `--artifacts core` to also download input
and output files, or `--artifacts full` to include recordings and event traces.

The upstream dataset currently declares no license in its dataset card. Confirm
usage rights before training, redistribution, or commercial use.

## Verifier

With AutoCAD running, verify a candidate DWG against one sample:

```powershell
python verifier/verify.py `
  --sample-dir samples/<workflow-id> `
  --candidate-dwg path/to/candidate.dwg `
  --write-scene results/<workflow-id>/scene.json `
  --output results/<workflow-id>/verdict.json
```

The verifier reports deterministic hard gates, native-dimension matches, rubric
checks with evidence, and explicit coverage. Rubrics that cannot yet be proven
from the extracted scene are marked `unverified` rather than guessed.

### Visual rubric verifier

The optional Codex VLM verifier evaluates only those `unverified` rubrics from
candidate and reference images. It uses structured output, rejects tool-using
runs, and accepts `pass` or `fail` only at confidence `>= 0.85` by default:

```powershell
python -m verifier.vlm.evaluate `
  --sample-dir samples/<workflow-id> `
  --deterministic-verdict runs/<workflow-id>/verdict.json `
  --candidate-image runs/<workflow-id>/candidate.png `
  --reference-image samples/<workflow-id>/input_files/reference.png `
  --output runs/<workflow-id>/vlm-verdict.json
```

The deterministic verifier remains authoritative: a VLM pass can resolve a
coverage gap but cannot override a deterministic failure. Low-confidence or
uncertain results leave the combined verdict `incomplete`. The rectangle pilot's
six visual rubrics raised combined coverage from 81.25% to 100% in child run
`20260827-rectangle-vlm-eval`.

See [verifier/vlm/README.md](verifier/vlm/README.md) for the provider interface,
result contract, rendering command, and ledger integration.

## Run ledger

Every agent execution should use an immutable run record. Query a reusable
verified DWG before starting new CAD work:

```powershell
python scripts/run_ledger.py reuse --sample-id <workflow-id>
```

Start and inspect runs with `start`, `attempt`, `artifact`, `event`, `ingest-mcp`,
`finish`, `list`, `show`, `diff`, `verify-integrity`, and `reindex`. The completed
rectangle pilot is stored as run `20260827-rectangle-pilot` with nine linked
attempts. Its VLM evaluation is stored separately as child run
`20260827-rectangle-vlm-eval`.

Source-control policy is prepared in the workspace `.gitignore` and
`.gitattributes`: Git tracks code and evaluation definitions, while the ledger
tracks DWGs, logs, trajectories, and indexes. Initialize and commit Git from the
workspace owner's shell; this managed sandbox cannot retain a readable `.git`
directory because its execution account has a different Windows owner SID.

See [ARCHITECTURE.md](ARCHITECTURE.md) for storage, source-version, trajectory,
reuse, and production-hardening decisions.

## Codex model batch

`scripts/batch_codex.py` runs each sample/model pair in an isolated directory
while using one AutoCAD instance sequentially. Every job records Codex JSONL,
MCP calls, model usage, DWG, extracted scene, verifier result, and ledger hashes.

Run the three-task smoke matrix:

```powershell
python scripts/batch_codex.py --campaign smoke-<date>
```

Run or resume one model/sample pair:

```powershell
python scripts/batch_codex.py `
  --campaign smoke-<date> `
  --model gpt-5.6-terra `
  --sample <workflow-id> `
  --reasoning-effort medium
```

Resume preserves an incomplete job directory and writes the replacement to a
numbered `.retry-NNN` directory. Interrupted, timed-out, and harness-error jobs
remain in the trajectory but do not suppress the replacement run.

### Adaptive self-improvement

An adaptive run gives a separate Codex supervisor the complete typed diagnostic:
process exit state and traceback, verifier verdict and completed checks, MCP tool
errors, artifact paths and hashes, and the actions currently permitted. The
supervisor may repair the drawing, retry a failed subsystem, or authorize a
candidate prompt, skill, MCP, verifier, or test change. Infrastructure failures
are not converted into drawing failures.

Every system edit is made in a complete isolated workspace under
`improvement/adaptive/<session>/workspace`. Approved-file checks, syntax and
component tests, hashes, version snapshots, and automatic rollback run before
the next CAD attempt. Production source, task data, rubrics, trajectories, and
the holdout split remain immutable.

Run a development sample through the online loop:

```powershell
python scripts/batch_codex.py `
  --campaign adaptive-dev `
  --model gpt-5.5 `
  --sample <development-workflow-id> `
  --adaptive-session adaptive-001 `
  --max-iterations 8 `
  --min-coverage 80 `
  --job-time-budget 7200 `
  --stagnation-limit 2
```

`--max-iterations` is a safety budget, not a fixed number of drawing repairs.
The supervisor can stop earlier on success, a non-retryable condition, exhausted
evidence, or repeated state. Holdout samples cannot be used in adaptive mode.
In adaptive mode, a nominal verifier pass below `--min-coverage` is a
`coverage_gap`, not success; the supervisor must address or explicitly stop on
the unverified evidence.
Inspect the durable decision and version history with:

```powershell
python scripts/adaptive_codex.py status --session adaptive-001
```

### Self-improvement proposals

Initialize the immutable 40-development/10-holdout split and inspect historical
failure ownership:

```powershell
python scripts/system_improve.py init-split
python scripts/system_improve.py collect
```

Create an isolated proposal and let a Codex improvement agent edit only candidate
copies:

```powershell
python scripts/system_improve.py create `
  --proposal improve-001 `
  --component prompt --component skill --component mcp --component verifier
python scripts/system_improve.py agent --proposal improve-001 --model gpt-5.6-sol
python scripts/system_improve.py validate --proposal improve-001
```

After adaptive development produces a stable candidate, use the resumable A/B
orchestrator for offline confirmation. A/B does not grant either evaluated CAD
agent source-edit permission: it compares the frozen production profile (A) with
the frozen candidate profile (B), runs tests, builds reports, and applies the
promotion gate:

```powershell
python scripts/run_ab.py `
  --proposal improve-001 `
  --baseline-campaign baseline-50 `
  --candidate-campaign candidate-50 `
  --model gpt-5.5
```

Its heartbeat and phase state are stored under
`improvement/campaigns/<baseline>__<candidate>/status.json`, with one log per
phase. Evaluate production and proposal profiles manually when finer control is
needed:

```powershell
python scripts/batch_codex.py --campaign baseline-50 --model gpt-5.6-sol --all-samples
python scripts/batch_codex.py --campaign candidate-50 --model gpt-5.6-sol --all-samples --proposal improve-001
python scripts/system_improve.py report --results batch/baseline-50/results.json `
  --output improvement/proposals/improve-001/baseline-report.json `
  --model gpt-5.6-sol --tests-passed
python scripts/system_improve.py report --results batch/candidate-50/results.json `
  --output improvement/proposals/improve-001/candidate-report.json `
  --model gpt-5.6-sol --tests-passed
python scripts/system_improve.py gate --proposal improve-001 `
  --baseline-report improvement/proposals/improve-001/baseline-report.json `
  --candidate-report improvement/proposals/improve-001/candidate-report.json
```

Only a gate-passed proposal can be promoted. Promotion archives before/after
source; rollback restores the archived previous version:

```powershell
python scripts/system_improve.py promote --proposal improve-001
python scripts/system_improve.py rollback --release improve-001
```

The recommended first matrix is in [batch-models.json](batch-models.json). The
initial simple-3D comparison is stored in
[batch/smoke-3d-model-comparison.json](batch/smoke-3d-model-comparison.json).
