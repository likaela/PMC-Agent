# Verify the real production build with the locally encrypted formal accounts.
. (Join-Path $PSScriptRoot 'common.ps1')
$vault=Import-ReviewEnvironment
$oldEnv=@{}
foreach ($name in @('PMC_E2E_USER_A','PMC_E2E_USER_B','PMC_E2E_USER_C','PMC_E2E_PASSWORD','PMC_E2E_PASSWORD_B','PMC_E2E_PASSWORD_C','PMC_REVIEW_E2E_OUTPUT')) {
    $oldEnv[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
}
$settings=Read-ReviewJson $reviewSettings
$sourcePaths=@('facts_path','inventory_path','units_path','quantity_path','slim_dataset_path') | ForEach-Object { Join-Path $reviewRoot $settings.$_ }
$before=@($sourcePaths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
try {
    foreach ($key in @('A','B','C')) {
        [Environment]::SetEnvironmentVariable('PMC_E2E_USER_'+$key,$vault.Accounts[$key].User,'Process')
        $name=if ($key -eq 'A') { 'PMC_E2E_PASSWORD' } else { 'PMC_E2E_PASSWORD_'+$key }
        [Environment]::SetEnvironmentVariable($name,(Unlock-ReviewValue $vault.Accounts[$key].Password),'Process')
    }
    # Stop/start only recorded deployment PIDs. Each independent phase keeps the
    # persistent owner/session store, but does not weaken the production rate limit.
    $prefix=-join ([char[]]@(0x6700,0x65B0,0x7CBE,0x7B80))
    $cases=@(,@('--grep-invert',$prefix))
    $spec=Join-Path $reviewRoot 'pmc-agent-frontend-main/frontend/review-tests/default-scope.spec.ts'
    foreach ($line in (Get-Content -LiteralPath $spec -Encoding UTF8)) {
        if ($line -match '^test\("([^\"]+)"') { $cases+=,@('--grep',[regex]::Escape($Matches[1])) }
    }
    if ($cases.Count -ne 5) { throw 'Expected all four production guide acceptance groups.' }
    for ($i=0; $i -lt $cases.Count; $i++) {
        & (Join-Path $PSScriptRoot 'stop.ps1')
        & (Join-Path $PSScriptRoot 'start.ps1')
        $env:PMC_REVIEW_E2E_OUTPUT=Join-Path $reviewRuntime ('acceptance-phase-'+$i)
        Push-Location (Join-Path $reviewRoot 'pmc-agent-frontend-main/frontend')
        try {
            & npm.cmd test -- --config playwright.review.config.ts @($cases[$i])
            if ($LASTEXITCODE -ne 0) { throw 'Formal authenticated HTTP/browser acceptance failed.' }
        } finally { Pop-Location }
    }
    & (Join-Path $PSScriptRoot 'health.ps1')
    Write-Host 'Formal accounts and production build passed local acceptance. Review remains on loopback only.'
} finally {
    foreach ($name in $oldEnv.Keys) { [Environment]::SetEnvironmentVariable($name,$oldEnv[$name],'Process') }
    $after=@($sourcePaths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
    if ([string]::Join('|',$before) -ne [string]::Join('|',$after)) { throw 'An approved read-only source changed during acceptance.' }
    Write-Host 'Enterprise facts, inventory Excel, confirmations and approved dataset are unchanged.'
}
