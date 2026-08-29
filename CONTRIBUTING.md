# Contributing

CAD-EvoLoop is developed as a reproducible research artifact. Contributions
must preserve evidence lineage and evaluation isolation.

## Development

1. Create an environment with Python 3.11 or newer.
2. Install the project in editable mode with test dependencies.
3. Run the complete test suite before submitting a change.

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Do not commit CAD-1000-Hours assets, DWG files, model credentials, AutoCAD job
directories, or generated experiment records. New metrics and figures must be
derived from immutable campaign manifests and ledger records.

System-changing agent proposals must remain isolated until static validation,
tests, development regression, and independent evidence review pass.
