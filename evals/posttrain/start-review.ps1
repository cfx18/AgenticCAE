param(
    [string]$Bundle = "reports/generated/posttrain-pilot-review-v1",
    [int]$Port = 8772,
    [string]$Catalog = ""
)
$ErrorActionPreference = "Stop"
$Workspace = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$BundlePath = (Resolve-Path (Join-Path $Workspace $Bundle)).Path
if (-not $BundlePath.StartsWith($Workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Review bundle must stay in the workspace"
}
$Python = Join-Path $Workspace ".local/posttrain-env/Scripts/python.exe"
$CatalogArgs = @()
if ($Catalog) {
    $CatalogPath = (Resolve-Path (Join-Path $Workspace $Catalog)).Path
    if (-not $CatalogPath.StartsWith($Workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Catalog must stay in the workspace" }
    $CatalogArgs = @("--catalog", "`"$CatalogPath`"")
}
$Expected = (Get-Content -LiteralPath (Join-Path $BundlePath "review-data.json") -Raw -Encoding UTF8 | ConvertFrom-Json).bundle_sha256
$Listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($Listening) {
    if ($Catalog) { throw "Port $Port is already in use; a presentation update requires an explicit server restart" }
    $Current = Invoke-RestMethod "http://127.0.0.1:$Port/data/review-data.json" -TimeoutSec 10
    if ($Current.bundle_sha256 -ne $Expected) { throw "Port $Port is occupied by a different review bundle" }
    Write-Output "Already serving http://127.0.0.1:$Port/"
    exit 0
}
$LogRoot = Join-Path $Workspace ".local/logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $Workspace "src"
    $Arguments = @("-u", "-m", "cad_evoloop.posttrain.review", "serve", "`"$BundlePath`"", "--port", "$Port") + $CatalogArgs
    $Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Workspace -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogRoot "posttrain-review-$Stamp.out.log") -RedirectStandardError (Join-Path $LogRoot "posttrain-review-$Stamp.err.log")
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $Health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($Health.ok) {
            Write-Output "Serving http://127.0.0.1:$Port/ (launcher PID $($Process.Id))"
            exit 0
        }
    } catch { }
    if ($Process.HasExited) { throw "Review server exited; inspect $LogRoot" }
}
throw "Review server did not become healthy; inspect $LogRoot"
