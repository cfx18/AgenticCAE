param(
    [string]$AutoCADDir = $env:AUTOCAD_MANAGED_DIR,
    [string]$OutputDir = ".local/autocad-topology"
)

$ErrorActionPreference = "Stop"
if (-not $AutoCADDir) { $AutoCADDir = "E:\AutoCAD\AutoCAD 2024" }
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$source = Join-Path $PSScriptRoot "EvoCadTopology.cs"
$output = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path $OutputDir
New-Item -ItemType Directory -Force -Path $output | Out-Null

& $compiler /nologo /target:library /optimize+ "/out:$output\EvoCadTopology.dll" `
    "/reference:$AutoCADDir\accoremgd.dll" `
    "/reference:$AutoCADDir\acdbmgd.dll" `
    "/reference:$AutoCADDir\acdbmgdbrep.dll" `
    "/reference:$AutoCADDir\acmgd.dll" `
    $source
if ($LASTEXITCODE -ne 0) { throw "C# compiler exited with $LASTEXITCODE" }
Write-Output "$output\EvoCadTopology.dll"
