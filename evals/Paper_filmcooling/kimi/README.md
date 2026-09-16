# Kimi Code + K3 paper-to-CAD run

This experiment gives Kimi Code the paper and the existing audited AutoCAD MCP. It does not
provide a human-authored geometry specification or require a particular CAD representation.

## Configure

Edit `.env` and fill these two values:

```dotenv
KIMI_MODEL_BASE_URL=https://your-kimi-endpoint/v1
KIMI_MODEL_API_KEY=your-api-key
```

The file is ignored by Git. The runner injects its values into the Kimi process without writing
the API key into `command.json`, `run.json`, the prompt, or the MCP audit.

## Run

From the repository root:

```powershell
.\evals\Paper_filmcooling\kimi\start-kimi-k3.ps1
```

Use `-Campaign name` to choose a stable run name. Each run stores the staged PDF, exact prompt,
Kimi stream events, stderr, Kimi session data, AutoCAD MCP audit, discovered DWGs, and a file
inventory under `evals/Paper_filmcooling/runs/<campaign>`.

An interrupted outer process can resume the same Kimi session without repeating paper analysis:

```powershell
.\evals\Paper_filmcooling\kimi\start-kimi-k3.ps1 -Campaign <campaign> -Resume
```
