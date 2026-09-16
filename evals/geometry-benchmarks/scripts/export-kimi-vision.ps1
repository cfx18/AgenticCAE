param(
    [ValidateSet(2,4,10)][int]$Sample = 2,
    [ValidateSet('evocad','direct')][string]$Harness = 'evocad',
    [switch]$All
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$samples = if ($All) { @(2,4,10) } else { @($Sample) }
$exports = @{}
foreach ($number in $samples) {
    $campaign = if ($Harness -eq 'evocad') { 'evocad-kimi-k3-omnimech-2-4-10-20260916' } else { "direct-kimi-k3-omnimech$number-20260916" }
    $job = Join-Path $root "evals/geometry-benchmarks/batch/$campaign/omnimech-$number/kimi-k3"
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $relative = "reports/generated/kimi-vision-$Harness-omnimech$number-$stamp"
    & (Join-Path $root '.local/geometry-env/Scripts/python.exe') (Join-Path $PSScriptRoot 'export_kimi_visual_trace.py') --job $job --output (Join-Path $root $relative)
    if ($LASTEXITCODE -ne 0) { throw 'Visual trace export failed; published page unchanged.' }
    $exports["kimi-vision-$Harness-$number.html"] = "$relative/index.html"
}
$configPath = Join-Path $root 'apps/geometry-review/catalog.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $config.PSObject.Properties['supplemental_pages']) {
    $config | Add-Member -NotePropertyName supplemental_pages -NotePropertyValue ([PSCustomObject]@{})
}
foreach ($name in $exports.Keys) {
    $config.supplemental_pages | Add-Member -NotePropertyName $name -NotePropertyValue $exports[$name] -Force
}
$defaultPage = if ($config.supplemental_pages.PSObject.Properties['kimi-vision-direct-2.html']) {
    $config.supplemental_pages.'kimi-vision-direct-2.html'
} else { $exports["kimi-vision-$Harness-$($samples[0]).html"] }
$config.supplemental_pages | Add-Member -NotePropertyName 'kimi-vision.html' -NotePropertyValue $defaultPage -Force
$temporary = "$configPath.vision-tmp"
[IO.File]::WriteAllText($temporary, ($config | ConvertTo-Json -Depth 30) + "`n", [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $configPath -Force
& (Join-Path $PSScriptRoot 'refresh-kimi-review.ps1')
Write-Output 'Visual trace: http://127.0.0.1:8770/kimi-vision.html'
