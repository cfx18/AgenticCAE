# Post-Training Task Pilot

Status: **20 mechanically checked candidates, pending human review**.
Date: 2026-09-16. Scope: noncommercial research. All source additions, downloaded
data, runtime packages, generated artifacts and logs are inside this workspace.
The initial build used trusted reference execution only. A subsequent Kimi K3
perception smoke uses the native Kimi Code CLI with a restricted public-only MCP
surface; see `docs/experiments/posttrain-kimi-smoke-and-xifeng-20260916.md`.
No fine-tuning, RL run or native AutoCAD job is part of this pilot.

## Deliverables

- Review: <http://127.0.0.1:8772/>, separate from the existing model-run review.
- Task evidence: `evals/data/posttrain/pilot-r4/`.
- Frozen review: `reports/generated/posttrain-pilot-review-v1/`.
- Human ledger: `reports/generated/posttrain-pilot-review-v1/human-reviews.jsonl`.
  It is created only when a human submits a review. No fake human records were
  inserted during testing. Records use the existing `HumanReviewStore` and bind
  to frozen inputs, answers, verifier evidence and UI hashes.
- Source probe: `evals/data/sources/fusion360gallery/posttrain-fusion-r1/`.
- Separate runtime: `.local/posttrain-env/`; the existing geometry environment
  and benchmark code/configuration were left unchanged.

The review shows public input, private answers, interactive synchronized GT and
comparison models, negative controls, reference tool receipts and source records.
Input drawings can be opened at native resolution. Review drafts are isolated
per task. Review decisions do not silently change the task or verifier.

## Actual Acceptance Results

- 32 source parts acquired from the official Fusion Gallery reconstruction
  `r1.0.1` archive, restricted to its upstream training identities.
- 20 candidate tasks using 16 distinct source parts from 14 parent project/file
  groups. These are not claims of 16 independent mechanical families.
- Allocation: 4 line-role, 3 dimension-attachment, 3 cross-view, 3 clarification,
  3 local-repair, 2 projection-diagnosis and 2 reconstruction tasks.
- 20/20 reference answers pass; all 52 negative controls are rejected.
- 20/20 reset input inventories repeat. Final grading binds to submitted
  snapshots, not later working-file edits or the best intermediate model.
- 0 human-accepted tasks. This is **not a 100% model accuracy result**.
- Regression suite: 70 passed, 2 skipped. The skipped existing geometry-review
  tests need optional `trimesh`, absent from the new minimal runtime.
- Browser checks: desktop 1600x1000 and mobile 390x844; loaded images, no page
  overflow, nonblank visible geometry, shared-camera orbit, draft isolation,
  and no browser errors. No human review is submitted by these tests.

Reproduction commands, run from the project root:

```powershell
$env:PYTHONPATH = "$PWD/src"
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.sources .local/datasets/evocad/fusion-new-probe --count 32
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.build evals/data/sources/fusion360gallery/posttrain-fusion-r1 .local/posttrain/new-pilot
.local/posttrain-env/Scripts/python.exe -m cad_evoloop.posttrain.review export .local/posttrain/new-pilot reports/generated/new-pilot-review
./evals/posttrain/start-review.ps1
```

The last command starts or reuses the current frozen pilot review on port 8772.
Pass `-Bundle reports/generated/new-pilot-review -Port 8773` to serve a new
export without replacing an existing listener. Builders reject existing output
directories instead of overwriting evidence. Package versions and generator
file hashes used for the accepted pilot build are in `pilot-r4/environment.json`.
The small top-level dependency list is in `evals/posttrain/requirements-geometry.txt`;
the environment record, not that list alone, captures transitive versions.

Tests:

```powershell
.local/posttrain-env/Scripts/python.exe -m pytest tests/test_posttrain.py tests/test_isolation.py tests/test_geometry_review.py -q --basetemp .local/test-tmp/posttrain-check
# Set NODE_PATH to an available Playwright installation before this command.
node tests/posttrain-review-browser.cjs
```

Browser artifacts: `.local/reports/posttrain-ui/`. Local server logs:
`.local/logs/posttrain-review-*.log`.

## Source And Gold Boundaries

Source: <https://github.com/AutodeskAILab/Fusion360GalleryDataset>.
Archive ETag: `"e7b0f6ddfa37a54e6b55b45e217d067f-123"`, 2,103,449,157 bytes.
The successful bounded acquisition transferred 19,889,308 bytes rather than
downloading the whole archive. An earlier slow direct connection was stopped;
that incomplete attempt is not included in the successful transfer count.
Range responses, archive identity, member sizes, paths and extracted hashes
are checked. Source JSON, STEP, thumbnails, original split and license are kept.
The source license remains its custom noncommercial license, not our project
license. No complete upstream dataset is redistributed.

The CAD parts are human-designed, but these drawings and questions are generated
for this pilot. They are not represented as original expert requests or human
engineering drawings. Original JSON units are cm; imported STEP geometry is read
by OCCT in mm. Tasks explicitly normalize the BRep bounding minimum to the origin
and record the translation. No mirroring or candidate alignment is allowed.

Line roles come from visibility-aware OCCT HLR plus explicitly drawn dimensions
and extension lines. The public artifact is raster-only; private primitive roles
and marker coordinates stay evaluator-side. HLR projected curves are not falsely
identified as persistent original BRep edges. Labels remain subject to expert
review, especially overlapping projected geometry.

Clarification tasks have a second, valid, geometrically different BRep with an
effectively identical displayed end-view projection. Thus rejecting a unique
axial-length answer has a constructive witness, not merely an LLM opinion.
These tasks do not imply that axial length is the only missing constraint.

Geometric task checks use a fixed-frame solid validity check and BRep missing/
extra volumes with absolute tolerances. They do not compare source-code strings,
reward self-reported dimensions or accept matching volume alone. Small-feature
and same-volume/wrong-shape controls are included in unit tests. This pilot
verifier is not yet a calibrated reward for arbitrary imported CAD.

## Issues Discovered And Retained

1. The old CadQuery 2.8 environment printed results but exited with status 1.
   A separate CadQuery 2.6.1 / OCCT 7.8.1.1.post1 environment passes cleanly.
   Existing runtime dependencies were not modified.
2. Build r1 exposed an absolute/relative path bug in acceptance recording.
   It remains as a failed build, not an accepted dataset or model failure.
3. Selecting the smallest cylindrical radius mislabeled a stepped shaft as a
   hole. The implementation now checks inward surface normal and full angular
   span; a regression distinguishes external shaft surfaces from internal bores.
   `repair-02` now uses an actual internal cylindrical feature on another part.
4. OCCT produced non-transitive Boolean comparisons for imported versus re-cut
   periodic faces on the ring. An independently constructed three-cylinder ring
   was checked against the original BRep and analytic volume, and used as that
   fixture's canonical target. The original normalized STEP and equivalence
   evidence are preserved. Contradictions between Boolean non-overlap and point
   classification now fail as inconclusive, not as model negative reward. This
   guard is a diagnostic, not a general proof of kernel correctness.
5. A browser screenshot initially caught a stale hidden canvas during a tab
   transition. Loading is now initialized synchronously; browser pixel tests
   refuse to inspect hidden canvases. Desktop and mobile were rerun successfully.

Failed builds r1/r2 and intermediate r3 remain under `.local/posttrain/`.
They are not exported as the active review set. No model was blamed for these
data, rendering or verifier implementation failures.

## Execution Boundary

`Episode` implements reset, observation, public observation conclusions,
checkpointing, submission and hash-chained receipts. Trusted reference scripts
were generated by the builder and replayed locally; no downloaded code was
executed. The reference traces are explicitly labeled as fixtures, not model
reasoning or agent attempts.

`DockerExecutor` requires a digest-pinned image, only mounts public input and
episode work, disables network access, and sets resource limits. It never falls
back to running arbitrary model code on the host. It has command-contract tests,
**not an end-to-end container security validation**: Docker is unavailable here.
Do not call this pilot a deployed or security-audited RL environment. The learner
and all of its filesystem/tool access must also be confined before real runs;
isolating only its CAD subprocess would not protect GT from an unrestricted
host-side coding agent. The human review server deliberately exposes GT and must
not be reachable from the learner sandbox.

## Review Gate And Remaining Work

Review the input sufficiency, GT correctness and verifier validity independently.
Suggested starting points: `line-01`, `line-03`, `observe-02`, `repair-01`,
`repair-02`, and `reconstruct-01`. A positive automated check is not a human
endorsement. Ratings below 4 or unresolved issues prevent an acceptance selection
in the UI. No SFT exporter currently consumes these ratings automatically.

Before hundreds of tasks or training:

- Adjudicate the 20 tasks and record revisions as new evidence versions.
- Add genuine feature-level dimension anchors, centerlines, hatching, true
  sections and stronger cross-view inference. Current cross-view items mostly
  exercise dimension-to-axis mapping; they are not a depth-reasoning benchmark.
- Add real drawing/expert-request transfer checks and human naturalness review.
  IterCAD and neuralCAD-Edit are not yet imported into this accepted pilot.
- Deduplicate by parent design and template before assigning training/eval splits;
  OmniMech 2/4/10 remain outside this training candidate set.
- Provision and penetration-test a learner sandbox and dedicated CAD workers.
  Native AutoCAD protocol/recovery is a separate track, not validated here.
- Add reviewed SFT exports and RL adapters/reward calibration. The current task
  grader is an acceptance checker, not the previously proposed full RL reward.
