$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$listeners = @(Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $server = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($server.CommandLine -notlike '*cad_evoloop.cli geometry-review-serve*' -or
        $server.CommandLine -notlike '*direct-codex-sol-ultra-omnimech2-https-20260914-review*' -or
        $server.CommandLine -notlike '*apps/geometry-review/catalog.json*') {
        throw 'Port 8770 is not the expected EvoCAD catalog server; leaving it untouched.'
    }
    Stop-Process -Id $server.ProcessId -ErrorAction Stop
}
if ($listeners.Count) { Start-Sleep -Milliseconds 750 }
& (Join-Path $root 'apps/geometry-review/start-review.ps1') -View direct
