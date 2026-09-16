# BenchCAD IR comparison launch, 2026-09-06

The baseline and specialist arms can run concurrently. Each has an independent
workspace, model conversation, process, stdout log and heartbeat. Both use
gpt-5.6-sol/medium, the fixed family-30-v1 selection, 12 outer iterations,
1800-second model-call timeout, 600-second execution timeout, and official
64-cubed voxel IoU after submission. A CAD action can execute multiple commands;
12 outer iterations is not an equal token or tool-call budget.

- `sol-family-30-v2`: completed forced-IR arm; same-thread perception and modeling.
- `sol-family-30-baseline-v1`: no required IR, still includes image feedback and reflection.
- `sol-family-30-specialist-v1`: independent perception conversation; new modeling
  conversation receives the IR and numerical image-verifier feedback only.
  Source target/views and overlays stay outside its workspace and attachments.
  It can render and inspect its own candidate. GT is reserved for final scoring.

The specialist design follows the original Ortho2CAD image-withheld diagnostic.
It changes both conversation separation and image visibility, so any difference
is the combined treatment effect, not a pure estimate of specialization alone.
The file boundary is an audited local-process policy, not OS-enforced isolation.
Independent runs also generate different IRs; this is not a fixed-IR handoff test.
Concurrent runs share account throughput, so elapsed times are not isolated
performance measurements. The historical forced arm ran separately.

## Monitoring and recovery

`python -m cad_evoloop.evaluation.benchcad_supervisor --campaign NAME --mode MODE`
can be launched through the existing `start_detached_campaign` process controller.
Each campaign persists `_control/status.json` every ten seconds, including child
PID, completed/scored counts, active sample and attempt count, launch history,
and exit status. Detailed invocation events remain in each sample directory.

Nonzero process exits allow at most two recovery launches. Completed results are
retained. Interrupted jobs are moved intact under `_interrupted/` with unique
names before rerunning; these are runtime-censored episodes, not extra scoring
attempts chosen by score. Human analysis must retain their cost and provenance.
No automatic retry is triggered by a low score. After the recovery budget is
exhausted the failure remains visible in the heartbeat and process-controller log.

At launch, baseline had 26 scored records. Its unfinished cable-routing-panel
episode had stopped updating at 2026-09-06 04:24 local time. Process enumeration
confirmed there was no active matching campaign before recovery.

## User-directed specialist stop and baseline completion

On 2026-09-06 the user requested no further specialist evaluation and completion
of the last baseline record only. Specialist remains an incomplete, stopped arm
with 3/30 scored records; retain all three results and interrupted episodes.
This outcome-dependent stop must be disclosed, and its partial mean must not be
presented as a completed 30-record comparison.

Before baseline recovery, both supervisors had exhausted their retries with
`FileNotFoundError: codex executable was not found`. Baseline had 29/30 scored
records; only `connector_faceplate_017071_s20260505` was unfinished. Process
enumeration confirmed neither campaign was running. The current installed Codex
binary passed `--version` (0.153.4). Its resolved directory was prepended to the
recovery process PATH, without changing global configuration. Baseline alone was
restarted at 2026-09-06T10:38:37Z with unchanged model, data and iteration limits;
the supervisor preserved the prior status and archived the incomplete episode.

Baseline recovery completed successfully at 2026-09-06T11:01:50Z: 30/30 records
scored, no active or non-scored records, supervisor exit code 0. The final
connector-faceplate episode took 1392.679 seconds and stopped autonomously after
11 iterations (not at the 12-iteration ceiling). Its submitted candidate scored
0.546358 official 64-cubed voxel IoU; its final image silhouette IoU was 0.842645.
These are different metrics and must not be reported interchangeably.

Across all 30 records, baseline mean official IoU is 0.7383129 and forced-IR mean
is 0.7412019, a forced-minus-baseline difference of 0.002889 (0.2889 percentage
points). These are descriptive means from one run per arm, not evidence of a
statistically established improvement. Specialist was not resumed. Final results
and trajectories remain under each campaign's record directories; baseline's
`_control/status.json` records successful completion.
