# CAD-EvoLoop

CAD-EvoLoop is a research system for evidence-grounded, self-improving CAD
agents. It connects a model-driven agent to AutoCAD through an unrestricted MCP
interface, verifies native CAD artifacts, attributes failures to the responsible
system layer, and records versioned repair trajectories.

The feasibility demo is complete. The repository is now entering research
engineering and large-scale evaluation; current three-sample results are not a
paper benchmark result.

## Current Components

- `mcp/`: audited AutoCAD and isolated Core Console execution.
- `evals/cad-1000-hours/verifier/`: deterministic and Codex VLM verification.
- `evals/cad-1000-hours/adaptive/`: typed diagnostics and adaptive sessions.
- `evals/cad-1000-hours/improvement/`: isolated candidate changes, gates, and
  rollback.
- `evals/cad-1000-hours/runledger/`: append-only trajectories, artifacts, source
  hashes, integrity checks, and run comparison.
- `.agents/skills/autocad-image-modeling/`: the project CAD skill.

The planned package boundaries, evaluation protocol, publication figures, and
release gates are in [docs/PROJECT_BLUEPRINT.md](docs/PROJECT_BLUEPRINT.md).

## Verification

Run the current test suite from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path 'evals/cad-1000-hours').Path
python -m pytest -q
```

The last verified state passed 68 tests. The temporary `PYTHONPATH` setup is a
known packaging gap that the planned `src/` migration will remove.

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
