# Provenance and Release Boundary

Audit date: 2026-08-29

## Project-authored material

The Python source, tests, prompts, project skill, schemas, and documentation in
this repository were developed for CAD-EvoLoop. They are released under
Apache-2.0 unless a file says otherwise.

## External software

- AutoCAD and AutoCAD Core Console are separately installed Autodesk products.
  No Autodesk executable, SDK, template, or drawing is distributed here.
- The AutoCAD bridge uses `pywin32` at runtime. Dependencies are installed from
  their original distributions and are not vendored.
- Codex is invoked as an external model runtime and visual-verifier provider.
  Model access, outputs, and service terms are separate from this repository.

Names such as AutoCAD, Autodesk, Codex, and Hugging Face are used only to
identify compatible external systems. No affiliation or endorsement is implied.

## CAD-1000-Hours

The evaluation preparation script references `markov-ai/cad-1000-hours` on
Hugging Face. The dataset card inspected on 2026-08-29 did not declare a license.
Consequently, the public source boundary excludes the complete local `samples/`
tree, including task descriptions, rubrics, metadata, inputs, outputs, videos,
and recordings.

The repository may publish workflow identifiers, cryptographic hashes,
preparation code, sealed split manifests, and aggregate statistics needed to
reproduce experiments without redistributing source assets. Users must obtain
the dataset from its publisher and comply with its terms.

## Generated and local material

The following are excluded from the source release:

- DWG, DWT, BAK, log, render, checkpoint, and Core Console job artifacts;
- batch outputs, run ledgers, model events, prompts containing local paths, and
  generated paper builds;
- credentials and local loader caches;
- downloaded or evaluator-only dataset artifacts.

Before a public release, run the provenance tests and inspect `git status` to
confirm that none of these classes is staged.
