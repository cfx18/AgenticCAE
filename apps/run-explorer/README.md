# Run Explorer

The Run Explorer is a static, local-first view over exported CAD-EvoLoop
campaign evidence. It does not call AutoCAD or a model.

```powershell
cad-evoloop explorer-export evals/cad-1000-hours/batch/pilot-v4-20260829 `
  --output reports/generated/pilot-v4-20260829/explorer --render-native
python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/apps/run-explorer/`. To inspect another export,
pass its workspace-root-relative JSON path as the `data` query parameter.
