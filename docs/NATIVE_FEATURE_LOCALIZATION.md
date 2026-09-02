# Native Feature Localization

EvoCAD's mesh verifier identifies connected surface-error regions in an aligned world frame. The native feature localization layer maps those regions back to AutoCAD's boundary representation so an Agent and a human reviewer can inspect likely responsible faces and modeling operations.

## Data path

1. `autocad_core_start` remains an unrestricted AutoLISP execution tool. Its optional `operation_manifest` records stable operation IDs and geometric intent without filtering or rewriting geometry code.
2. `autocad_topology_start/status/cancel` loads the workspace-built `EvoCadTopology.dll` in an isolated Core Console process and reads a DWG without saving changes.
3. The plugin exports solid/entity handles, 64-bit subentity IDs, face and edge fingerprints, analytic surface and curve parameters, loops, adjacency, bounds, mass properties, and exporter errors.
4. The verifier retains up to nine deterministic source-surface points per mismatch region. The plugin compensates for AutoCAD `STLOUT` translation, then computes each point's minimum distance to trimmed B-Rep surfaces and their boundary curves.
5. `geometry_features.py` uses exact query votes first, retains aligned face bounds as a fallback, constructs face adjacency, identifies conservative analytic-surface feature candidates, and joins declared operation provenance.
6. The enriched localization is stored in the immutable verifier verdict, feedback packet, run ledger, and review bundle.

## Evidence levels

- `candidate_topology_faces` records exact trimmed-face vote fractions and distances when the native query succeeds. A confidence-labelled spatial ranking remains available as a fallback.
- `engineering_feature_candidates` describes geometry such as an inward-oriented cylindrical surface. It does not claim that AutoCAD retained a parametric feature-history tree.
- `responsible_operation_candidates` requires a shared entity handle, face fingerprint, or feature ID from the recorded operation manifest. Missing provenance produces no invented operation link.
- Ground-truth STEP face identities remain evaluator-only. They are used to diagnose and score but are not exposed to the modeling action turn outside the sanitized verifier result.

## Build and deployment

The tracked source is `mcp/autocad-topology/EvoCadTopology.cs`. Runtime binaries are generated under `.local/autocad-topology/` and are not committed. `build_topology_plugin` compiles against the installed AutoCAD managed assemblies with the .NET Framework compiler. The standalone equivalent is:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File mcp/autocad-topology/build.ps1
```

Set `AUTOCAD_CORE_CONSOLE`, `AUTOCAD_MANAGED_DIR`, and `AUTOCAD_TOPOLOGY_PLUGIN` to override installation-specific paths.

## Current boundary

This version recovers native B-Rep topology, analytic geometry, and point-to-trimmed-face attribution, not a complete parametric construction history. Query accuracy on pathological or invalid B-Reps and sub-feature causality across destructive Boolean operations remain calibration targets. Those limitations are surfaced in the verdict rather than hidden behind a high-confidence label.
