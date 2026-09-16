[CmdletBinding()]
param(
    [string]$Campaign = ("thole-baseline-hole-kimi-k3-minimal-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [int]$TimeoutSeconds = 5400,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")).Path
$Python = Join-Path $Root ".local\geometry-env\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$Source = Join-Path $Root "evals\Paper_filmcooling\2022-Thole-Adiabatic Effectiveness Measurements for a Baseline Shaped Film Cooling Hole.pdf"
$Runner = Join-Path $Root "evals\Paper_filmcooling\scripts\run_paper_kimi.py"
$EnvFile = Join-Path $PSScriptRoot ".env"

if ($Resume) {
    $ResumeRunner = Join-Path $Root "evals\Paper_filmcooling\scripts\resume_paper_kimi.py"
    & $Python $ResumeRunner `
        --campaign $Campaign `
        --env-file $EnvFile `
        --timeout $TimeoutSeconds
    exit $LASTEXITCODE
}

& $Python $Runner `
    --source $Source `
    --campaign $Campaign `
    --env-file $EnvFile `
    --timeout $TimeoutSeconds

exit $LASTEXITCODE
