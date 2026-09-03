# Durable Campaign Runner

The geometry batch can run independently of the initiating terminal or Codex
conversation. All control state and logs remain inside the campaign directory.

## Start and inspect

```powershell
cad-evoloop agent-geometry-start <manifest.json> <selection.json> `
  --campaign <new-campaign-id> --model gpt-5.6-sol

cad-evoloop agent-geometry-status <campaign-id>
```

The runner writes these files under
`evals/geometry-benchmarks/batch/<campaign>/runner/`:

- `command.json`: exact child command;
- `runner-state.json`: PID, lifecycle timestamps, exit code, and error;
- `stdout.log` and `stderr.log`: durable process output.

`agent-geometry-status` also derives planned, recorded, terminal, strict-pass,
and active-sample counts from the campaign and project ledgers. Starting a
second live runner for the same campaign is rejected.

## Attempt recovery

Every new geometry job writes `recovery-state.json`. The state is updated with
an atomic replace at three boundaries:

1. `action_running`: an interrupted action is retried in the same attempt; its
   partial prompt, events, stderr, audit, and candidate are archived under
   `action-interruptions/iNNN/`.
2. `action_completed`: model and CAD work are retained; only export, topology,
   and geometry verification are replayed.
3. `verifier_completed`: action and verification are retained; reflection
   resumes the same Codex thread in the next immutable `decision-turns/tNN/`.

A completed attempt is copied into the recovery state before the loop advances.
The outer project kernel still reserves one work-unit retry as a final host
interruption guard. It does not create an additional geometry iteration.

Campaign manifests bind `geometry-attempt-checkpoint-v1` and the source hashes.
Old campaigns remain immutable and are not upgraded in place.
