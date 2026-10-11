. (Join-Path $PSScriptRoot 'common.ps1')
$recordPath = Join-Path $reviewRuntime 'processes.local.json'
if (!(Test-Path -LiteralPath $recordPath)) { Write-Host 'No recorded review processes.'; exit 0 }
foreach ($record in (Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json)) {
    if (Assert-ReviewProcess $record) {
        & taskkill /PID $record.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'A recorded review process could not be stopped.' }
    }
}
Write-Host 'Recorded local review processes stopped. Development and Trial processes were not touched.'
