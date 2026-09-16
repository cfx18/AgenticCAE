param(
    [ValidateSet('features', 'main', 'lineage', 'recovery', 'feedback', 'direct')]
    [string]$View = 'features',
    [switch]$All
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = Join-Path $root '.local/geometry-env/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing review runtime: $python"
}
$views = @(
    @{ Name = 'features'; Port = 8765; Bundle = 'agent-geometry-30-sol-v2-feature-review-display-v2'; Ledger = 'agent-geometry-30-sol-v2-feature-review-display-v2' },
    @{ Name = 'main'; Port = 8766; Bundle = 'agent-geometry-30-sol-v2-review'; Ledger = 'agent-geometry-30-sol-v2' },
    @{ Name = 'lineage'; Port = 8767; Bundle = 'agent-geometry-lineage-pilot-sol-v2-review'; Ledger = 'agent-geometry-lineage-pilot-sol-v2' },
    @{ Name = 'recovery'; Port = 8768; Bundle = 'agent-geometry-lineage-pilot-sol-v2-recovery1-review'; Ledger = 'agent-geometry-lineage-pilot-sol-v2-recovery1' },
    @{ Name = 'feedback'; Port = 8769; Bundle = 'agent-geometry-30-sol-human-feedback-v3-review'; Ledger = 'agent-geometry-30-sol-human-feedback-v3' },
    @{ Name = 'direct'; Port = 8770; Bundle = 'direct-codex-sol-ultra-omnimech2-https-20260914-review'; Ledger = 'direct-codex-sol-ultra-omnimech2-https-20260914' }
)
$logDir = Join-Path $root '.local/logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
foreach ($item in $views) {
    if (-not $All -and $item.Name -ne $View) { continue }
    $bundle = Join-Path $root ('reports/generated/' + $item.Bundle)
    $data = Join-Path $bundle 'review-data.json'
    if (-not (Test-Path -LiteralPath $data -PathType Leaf)) { throw "Missing frozen bundle: $data" }
    $expected = (Get-Content -LiteralPath $data -Raw -Encoding UTF8 | ConvertFrom-Json).bundle_sha256
    $url = 'http://127.0.0.1:' + $item.Port
    $running = $false
    try {
        $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
        $running = $health.ok -eq $true
    } catch { }
    if ($running) {
        $served = Invoke-RestMethod "$url/data/review-data.json" -TimeoutSec 10
        if ($served.bundle_sha256 -ne $expected) {
            throw "Port $($item.Port) serves another bundle; it has not been stopped."
        }
        if (-not $health.catalog) {
            throw "Port $($item.Port) runs the legacy single-bundle server. Restart that review server to enable Harness navigation."
        }
        Write-Output "$($item.Name): $url/ (already running)"
        continue
    }
    $probe = [Net.Sockets.TcpClient]::new()
    try {
        $probe.Connect('127.0.0.1', $item.Port)
        throw "Port $($item.Port) is occupied; its process has not been stopped."
    } catch [Net.Sockets.SocketException] {
        # A refused loopback connection means the port is available.
        if ($_.Exception.SocketErrorCode -ne [Net.Sockets.SocketError]::ConnectionRefused) { throw }
    } finally { $probe.Dispose() }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $logDir "review-$($item.Name)-$stamp.stdout.log"
    $stderr = Join-Path $logDir "review-$($item.Name)-$stamp.stderr.log"
    $arguments = @(
        '-u', '-m', 'cad_evoloop.cli', 'geometry-review-serve',
        "reports/generated/$($item.Bundle)", '--reviews',
        "evals/geometry-benchmarks/human-reviews/$($item.Ledger).jsonl",
        '--host', '127.0.0.1', '--port', [string]$item.Port,
        '--catalog', 'apps/geometry-review/catalog.json'
    )
    $process = Start-Process -FilePath $python -ArgumentList $arguments `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $process.Refresh()
        if ($process.HasExited) { throw "Review server exited. Inspect $stderr" }
        try {
            $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
            if ($health.ok) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Review server not ready. PID $($process.Id); log $stderr" }
    $served = Invoke-RestMethod "$url/data/review-data.json" -TimeoutSec 10
    if ($served.bundle_sha256 -ne $expected) { throw "Unexpected bundle at $url" }
    Write-Output "$($item.Name): $url/ (PID $($process.Id), $($served.runs.Count) runs)"
}
