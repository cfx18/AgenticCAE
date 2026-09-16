# EvoCAD Interview Review Guide

This repository intentionally excludes raw evaluation data from Git. To review the
demo, use the GitHub repository plus the separate `evals/data` archive.

## What To Share

- GitHub repository: `https://github.com/cfx18/AgenticCAE`
- Data archive: `AgenticCAE-evals-data-20260917.zip`
- SHA256 checksum file next to the archive.

The archive should be extracted at the repository root so the final layout is:

```text
AgenticCAE/
  evals/
    data/
      posttrain/
      sources/
```

## Reviewer Flow

On Windows PowerShell:

```powershell
git clone https://github.com/cfx18/AgenticCAE.git
cd AgenticCAE

# Extract the data archive here so evals/data exists.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r evals/posttrain/requirements-discovery.txt
.\evals\posttrain\start-drawing-review.ps1 -Python .\.venv\Scripts\python.exe -Restart
```

Open:

- Dashboard: `http://127.0.0.1:8775/results.html`
- Per-case review UI: `http://127.0.0.1:8775/?batch=hard&task=hard-15`

The dashboard summarizes KIMI reading behavior across drawing QA batches. The
per-case UI shows the original input drawing, model answer, verifier/adjudication
status, visual observation receipts, and review notes.

## What The Reviewer Should Look At

1. `results.html`: high-level outcome distribution, timeout rate, and cases where
   automatic grading needed human or semantic review.
2. `?batch=hard&task=hard-15`: a representative hard drawing case with visual
   evidence and model trajectory.
3. `?batch=spot-omnimech-4&task=omnimech4-line-01`: a focused diagnostic showing
   the line-role confusion failure mode.
4. `docs/FAILURE_PATTERNS_20260916.md`: the failure taxonomy derived from KIMI
   bad cases.
5. `docs/POSTTRAIN_DATA_FAMILIES_20260916.md`: the training/eval data family
   design and ground-truth availability.

## Data Notes

The data package is for non-commercial research review. It contains generated CAD
tasks, real drawing QA review bundles, KIMI observation traces, and provenance
records. Do not redistribute raw drawings or model session traces beyond the
intended review context.
