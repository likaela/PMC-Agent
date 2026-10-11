. (Join-Path $PSScriptRoot 'common.ps1')
$vault = Import-ReviewEnvironment
$recordPath = Join-Path $reviewRuntime 'processes.local.json'
if (Test-Path -LiteralPath $recordPath) {
    foreach ($record in (Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json)) {
        if (Assert-ReviewProcess $record) { throw 'This review deployment is already running.' }
    }
}
foreach ($port in @(8020,8090)) {
    $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port)
    try { $probe.Start() } finally { $probe.Stop() }
}
if (!(Test-Path -LiteralPath (Join-Path $env:PMC_REVIEW_WEB_ROOT 'index.html'))) { throw 'Build the isolated review frontend first.' }
Push-Location $reviewRoot
$records = @()
try {
    New-Item -ItemType Directory -Path $reviewRuntime -Force | Out-Null
    $validation = Start-Process -FilePath $reviewCaddy -ArgumentList 'validate --config deploy/review/Caddyfile --adapter caddyfile' -WorkingDirectory $reviewRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $reviewRuntime 'validation.out.log') -RedirectStandardError (Join-Path $reviewRuntime 'validation.err.log')
    if ($validation.ExitCode -ne 0) { throw 'Private proxy configuration is invalid.' }
    $backend = Start-Process -FilePath (Join-Path $reviewRoot 'venv/Scripts/python.exe') -ArgumentList 'scripts/run_authorized_review.py' -WorkingDirectory $reviewRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $reviewRuntime 'backend.out.log') -RedirectStandardError (Join-Path $reviewRuntime 'backend.err.log')
    $records += @{Id=$backend.Id; StartTicks=$backend.StartTime.ToUniversalTime().Ticks; Kind='backend'}
    $proxy = Start-Process -FilePath $reviewCaddy -ArgumentList 'run --config deploy/review/Caddyfile --adapter caddyfile' -WorkingDirectory $reviewRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $reviewRuntime 'proxy.out.log') -RedirectStandardError (Join-Path $reviewRuntime 'proxy.err.log')
    $records += @{Id=$proxy.Id; StartTicks=$proxy.StartTime.ToUniversalTime().Ticks; Kind='proxy'}
    $deadline = (Get-Date).AddSeconds(40)
    $ready = $false
    $plain = Unlock-ReviewValue $vault.Accounts.A.Password
    $auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($vault.Accounts.A.User + ':' + $plain)); $plain=$null
    while ((Get-Date) -lt $deadline) {
        try { $health = Invoke-ReviewLocalApi '/health' $auth; $ready=$health.model_egress -eq 'disabled'; if ($ready) { break } } catch { Start-Sleep -Milliseconds 250 }
        if ($backend.HasExited -or $proxy.HasExited) { break }
    }
    if (!$ready) { throw 'Local review startup failed. Inspect private runtime diagnostics; no public tunnel was started.' }
    $records | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding UTF8
    Write-Host 'Review running locally at http://127.0.0.1:8090 (authentication required). Backend: 8020. No public tunnel.'
} catch {
    foreach ($record in $records) { if (Assert-ReviewProcess $record) { & taskkill /PID $record.Id /T /F | Out-Null } }
    throw
} finally { Pop-Location; $auth=$null; $env:PMC_REVIEW_PROXY_SECRET=$null }
