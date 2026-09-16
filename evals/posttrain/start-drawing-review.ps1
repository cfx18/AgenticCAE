param(
    [int]$Port = 8775,
    [string]$Python = "python",
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$Workspace = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$DataRoot = Join-Path $Workspace "evals/data"
$HardBundle = "evals/data/posttrain/real-drawings/reviews/boxed-hard-r1-learner-review"

if (-not (Test-Path (Join-Path $Workspace $HardBundle))) {
    throw "Missing data bundle. Extract the EvoCAD data package at the repository root so evals/data exists."
}

$Listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($Listening -and $Restart) {
    Stop-Process -Id $Listening.OwningProcess -Force
    Start-Sleep -Milliseconds 800
} elseif ($Listening) {
    Write-Output "Already listening on http://127.0.0.1:$Port/. Use -Restart to replace the existing server."
    exit 0
}

$ReviewRoot = Join-Path $Workspace ".local/reports/drawing-results-ui"
$SourceApp = Join-Path $ReviewRoot "source/app"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ReportDir = Join-Path $ReviewRoot "report-$Stamp"
$CatalogPath = Join-Path $ReviewRoot "catalog-$Stamp.json"

New-Item -ItemType Directory -Force -Path $SourceApp | Out-Null
Copy-Item -Recurse -Force (Join-Path $Workspace "apps/posttrain-review/*") $SourceApp
Copy-Item -Force (Join-Path $Workspace "apps/geometry-review/geometry-viewer.js") (Join-Path $SourceApp "geometry-viewer.js")
Copy-Item -Recurse -Force (Join-Path $Workspace "apps/geometry-review/vendor") (Join-Path $SourceApp "vendor")

$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $Workspace "src"
    & $Python -m cad_evoloop.posttrain.results `
        (Join-Path $Workspace "evals/posttrain/drawing-results.json") `
        $ReportDir | Write-Output
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

$Catalog = [ordered]@{
    workspace_root = "../../.."
    app_dir = ".local/reports/drawing-results-ui/source/app"
    presentation_dir = ".local/reports/drawing-results-ui/snapshots"
    bundles = @(
        [ordered]@{ id = "long"; harness = "Kimi Code"; label = "Original long prompt"; bundle = "evals/data/posttrain/real-drawings/reviews/long-r1-review"; reviews = "evals/data/posttrain/real-drawings/reviews/long-r1-review/human-reviews.jsonl" },
        [ordered]@{ id = "boxed"; harness = "Kimi Code"; label = "Boxed local prompt"; bundle = "evals/data/posttrain/real-drawings/reviews/boxed-r2-learner-review"; reviews = "evals/data/posttrain/real-drawings/reviews/boxed-r2-learner-review/human-reviews.jsonl" },
        [ordered]@{ id = "hard"; harness = "Kimi Code"; label = "Context-hard drawings"; bundle = $HardBundle; reviews = "evals/data/posttrain/real-drawings/reviews/boxed-hard-r1-learner-review/human-reviews.jsonl" },
        [ordered]@{ id = "spot-omnimech-4"; harness = "Kimi Code"; label = "Spot diagnostic: OmniMech-4 line role"; bundle = "evals/data/posttrain/real-drawings/reviews/omnimech4-line-r2-learner-review"; reviews = "evals/data/posttrain/real-drawings/reviews/omnimech4-line-r2-learner-review/human-reviews.jsonl" }
    )
    supplemental_pages = [ordered]@{ "results.html" = ($ReportDir.Substring($Workspace.Length + 1).Replace("\", "/") + "/results.html") }
}
$CatalogJson = $Catalog | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($CatalogPath, $CatalogJson, [System.Text.UTF8Encoding]::new($false))

& powershell -ExecutionPolicy Bypass -File (Join-Path $Workspace "evals/posttrain/start-review.ps1") `
    -Bundle $HardBundle `
    -Port $Port `
    -Catalog ($CatalogPath.Substring($Workspace.Length + 1))
if ($LASTEXITCODE -ne 0) {
    throw "Review server failed to start"
}

Write-Output "Dashboard: http://127.0.0.1:$Port/results.html"
Write-Output "Default review case: http://127.0.0.1:$Port/?batch=hard&task=hard-15"
