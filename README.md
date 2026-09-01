# CAD-EvoLoop

CAD-EvoLoop is a research system for evidence-grounded, self-improving CAD
agents. It connects a model-driven agent to AutoCAD through an unrestricted MCP
interface, verifies native CAD artifacts, attributes failures to the responsible
system layer, and records versioned repair trajectories.

The feasibility demo and an eight-workflow, three-model development pilot are
complete. The repository is now entering verifier calibration and larger-scale
evaluation; pilot results are engineering evidence, not a paper benchmark.

## Current Components

- `src/cad_evoloop/backends/autocad/`: audited AutoCAD and isolated Core Console execution.
- `src/cad_evoloop/verification/`: deterministic and Codex VLM verification.
- `src/cad_evoloop/supervisor/`: typed diagnostics and adaptive system changes.
- `src/cad_evoloop/evaluation/`: sealed inputs, immutable campaigns, and EQC metrics.
- `src/cad_evoloop/ledger/`: append-only trajectories, artifacts, source hashes,
  integrity checks, and run comparison.
- `src/cad_evoloop/agent/`: model-neutral, event-sourced project state,
  resumable GoalGraph scheduling, typed engineering artifacts, stage contracts,
  external-operation reconciliation, Codex compatibility, and bounded context views.
- `apps/geometry-review/`: local expert adjudication of geometry evidence,
  verifier decisions, repair trajectories, and MCP failures.
- `.agents/skills/autocad-image-modeling/`: the project CAD skill.

The old `mcp/` and `evals/...` Python entry points remain compatibility wrappers.
The research roadmap and protocol are in
[docs/PROJECT_BLUEPRINT.md](docs/PROJECT_BLUEPRINT.md) and
[docs/EVALUATION_PROTOCOL.md](docs/EVALUATION_PROTOCOL.md). The independent
long-horizon runtime is described in
[docs/LONG_HORIZON_AGENT.md](docs/LONG_HORIZON_AGENT.md).
The cross-stage CAE design and experiment boundary are in
[docs/ENGINEERING_AGENT_ARCHITECTURE.md](docs/ENGINEERING_AGENT_ARCHITECTURE.md)
and [docs/EXPERIMENT_LOG.md](docs/EXPERIMENT_LOG.md).

## Verification

Install the package for development and run the suite from the repository root:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Stable CLIs are installed as `cad-evoloop`, `cad-evoloop-batch`,
`cad-evoloop-ledger`, `cad-evoloop-improve`, `cad-evoloop-eqc`, and
`cad-evoloop-report`. For example:

```powershell
cad-evoloop batch --campaign pilot-01 --all-samples --protocol-mode pilot
cad-evoloop campaign-verify evals/cad-1000-hours/batch/pilot-01/campaign-manifest.json
cad-evoloop report evals/cad-1000-hours/batch/pilot-01 --output reports/generated/pilot-01
cad-evoloop explorer-export evals/cad-1000-hours/batch/pilot-01 `
  --output reports/generated/pilot-01/explorer --render-native
cad-evoloop verifier-replay evals/cad-1000-hours/batch/pilot-01 `
  --campaign verifier-calibration-01 `
  --output evals/cad-1000-hours/improvement/campaigns/verifier-calibration-01
```

Every campaign seals model and execution settings, source hashes, split membership,
visible input hashes, evaluator-only hashes, and environment identity before the
first job starts.

The batch verifier fuses deterministic CAD evidence with an isolated Codex VLM
for rubric checks that remain `unverified`. The VLM receives rendered candidate
and reference images, has no MCP tools, and cannot override deterministic
failures. Fused EQC success, not the legacy nominal score, controls completion.

The local Run Explorer in `apps/run-explorer/` reads only exported campaign
data and cached images. Serve the repository root with a static HTTP server and
open `/apps/run-explorer/`; it never redraws a CAD artifact or calls a model.

Geometry campaigns use the separate review workbench in
`apps/geometry-review/`. Its loopback API writes hash-chained, immutable human
adjudications under `evals/geometry-benchmarks/human-reviews/`, so verifier
false positives, false negatives, data defects, and reviewer disagreement can
be audited against exact evidence versions.

## Data and Generated Artifacts

Downloaded CAD-1000-Hours assets, AutoCAD jobs, DWG files, run records, batch
outputs, and generated paper artifacts are local data and are excluded from
version control. The upstream dataset card does not currently declare a
license, so dataset assets must not be redistributed until the terms are
confirmed.

## License

Project-authored source and documentation are licensed under Apache-2.0. Dataset
assets, AutoCAD, model services, and generated artifacts remain under their own
terms; see [docs/PROVENANCE.md](docs/PROVENANCE.md).
