# Audited AutoCAD MCP

`src/cad_evoloop/backends/autocad/audited.py` loads the AutoCAD MCP shipped with the project skill,
preserves its unrestricted CAD command surface, and adds only execution and audit
infrastructure:

- `autocad_set_run_context` for `sample_id`, `run_id`, and `attempt_id` tagging;
- `autocad_start_command`, `autocad_command_status`, and
  `autocad_cancel_command` for responsive long-running command jobs;
- `autocad_checkpoint` for saving an idle document to a recoverable workspace DWG;
- `autocad_core_start`, `autocad_core_status`, and `autocad_core_cancel` for
  unrestricted AutoLISP in a disposable AutoCAD Core Console process;
- append-only, redacted tool-call audit events;
- timing and success/error status for each MCP call.

The wrapper discovers installed versioned COM ProgIDs such as
`AutoCAD.Application.24.3` when the generic `AutoCAD.Application` registration
is absent. The MCP process must run at the same Windows integrity level as the
AutoCAD process so it can access the application's Running Object Table entry.
The entry point also forces UTF-8 standard streams so localized COM exceptions
cannot corrupt or close the MCP transport.

`autocad_send_command` remains available for compatibility. Neither interface
filters AutoCAD commands, AutoLISP, or geometry operations. The asynchronous
interface serializes jobs only because one active AutoCAD document cannot safely
execute competing command streams.

Batch evaluation uses Core Console jobs by default. Each stage has its own input
DWG, output DWG, script, stdout, and stderr under `mcp/jobs/<job-id>`. Cancelling
or timing out a stage terminates only that Core Console process, leaving desktop
AutoCAD and completed checkpoints untouched.

Use `config.example.toml` as the project MCP configuration and restart the Codex
session after activation. The current managed environment exposes `.codex` as a
read-only loader path, so the active config may still point at the unaudited base
server until it is changed by the workspace owner.

At the start of each attempt, call `autocad_set_run_context`. After CAD work,
run `python evals/cad-1000-hours/scripts/run_ledger.py ingest-mcp --run <run-id>`
to merge matching audit records into the immutable run trajectory.
