# Astra OmniMech 2: Human-Requested Mirror Diagnostic

Date: 2026-09-14. The user noticed a possible mirror relation between Astra's
OmniMech 2 reconstruction and the evaluator GT and requested a reflection test.
This is GT-assisted post-hoc diagnosis, not an autonomous correction or a new
model run. Original Astra score and human reviews remain unchanged.

## Procedure

Source campaign: `direct-codex-astra-ultra-omnimech2-https-20260914`.
The original candidate STL was rescored unchanged and reflected about its bounding
box center separately along X, Y and Z. Triangle winding was corrected through
`trimesh.apply_transform`. The unchanged geometry-v2 verifier used 20,000 surface
samples and voxel resolution 64, retaining its 24 proper axis rotations and
translation, with no scaling or reflections added to the alignment policy.

All three single-axis reflections are equivalent up to proper rotations, so
their equal scores are expected; they are not three independent modeling trials.
The Y mirror was then reproduced on the native DWG, about WCS plane `y=32`:
`(x,y,z) -> (x,64-y,z)`. This changes handedness, not just the viewer camera.

AutoCAD command: `MIRROR3D`, ZX plane through `(0,32,0)`, replace source objects
in an isolated working copy only. See the [official command reference](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-Core/files/GUID-E769E87D-8502-4A1E-B6F8-03889F26F944.htm).
No dimensions, booleans, holes or other features were edited. The repaired DWG
was reopened for native topology and independently exported to STL for scoring.

## Results

- Unchanged control: score **91.69**, strict fail, IoU **0.890819**, normalized
  Chamfer **0.007152**. Exactly reproduces the original recorded metrics.
- X/Y/Z reflected meshes: score **100.0**, strict pass, IoU **1.000000**,
  normalized Chamfer **0.004571** in all three tests.
- Native Y-mirrored DWG re-export: score **100.0**, strict pass, IoU **1.000000**,
  normalized Chamfer **0.004546**. Bounding-box error 0, volume error **0.0483%**,
  surface-area error **0.0550%**, watertight candidate.
- Localized mismatch: 4 regions / 20.745% combined sampled fraction before;
  0 regions / 0% above the localization threshold after native mirroring.
- Native topology before/after: one Solid3d, no export errors, identical volume
  **25779.080613361337**, identical surface area **10834.4633812508**, same bounds
  `[-10,0,0] .. [33,64,22.1]` within floating-point precision.
- Native correction/export/evaluation took **54.204 seconds**, zero model calls.

The principal discrepancy against this GT is a mirror relation, rather than
incorrect dimensions. This test does not decide whether the source drawing or
GT convention is authoritative on handedness; that needs source-view review.
IoU 1 is voxel equality at this resolution, not exact B-Rep identity. Sampled
Chamfer has a nonzero sampling floor; GT tessellation is itself non-watertight.
Do not interpret 100 as manufacturing validation or change the original score.

## Provenance And Review

- Original DWG SHA: `31bf9f7c5de9dfec19486bab66f2f4f34b3ce960d734b542b1b8942f1ac59688`.
- Mirrored DWG SHA: `f9d2d78d2931fb8d56575dc64536bf1b97029f6754e8cfb9561ba94cbdc40eb5`.
- GT SHA: `beec5dbcffa47608dd0082b0185b46b127c67b3e37be5868c6d01e95df299889`.
- Diagnostic review SHA: `5af869d026270b96bb56ecf529b41f147c30d62b97ef2222216e1a04f5367332`.
- Mesh transforms, full verdicts and protected hashes:
  `evals/geometry-benchmarks/diagnostics/astra-omnimech2-mirror-20260914/`.
- Native derivative and provenance:
  `evals/geometry-benchmarks/batch/human-mirror-astra-omnimech2-20260914/`.
- Separate ledger links to the original run by `parent_run_id`; integrity verified
  for 22 files and 20 events. Original DWG, original verdict/results and GT hashes
  were checked unchanged. Original frozen review is not overwritten.
- [Interactive before/after review](http://127.0.0.1:8770/?view=mirror-astra-2):
  Harness **Diagnostics**, experiment **OmniMech 2 - Astra + human mirror**.
  Left-hand runs retain the unchanged original and the human-guided derivative.
  The diagnostic has its own review ledger; existing reviews are not copied.
- Browser verified complete input, nonblank geometry, synchronized rotation,
  mirror/original score bindings and no error/warning messages.
- Regression checks: 35 Python tests and 6 Node navigation tests passed.

Reproduction scripts (refuse to overwrite experiment output):
`evals/geometry-benchmarks/scripts/mirror_diagnostic.py` and
`evals/geometry-benchmarks/scripts/astra_omnimech2_mirror.py`.
