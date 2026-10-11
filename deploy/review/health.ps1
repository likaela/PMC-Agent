. (Join-Path $PSScriptRoot 'common.ps1')
$vault = Import-ReviewEnvironment
try {
    foreach ($key in @('A','B','C')) {
        $account=$vault.Accounts[$key]; $plain=Unlock-ReviewValue $account.Password
        $auth=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($account.User+':'+$plain)); $plain=$null
        $health=Invoke-ReviewLocalApi '/health' $auth
        $catalog=Invoke-ReviewLocalApi '/api/v1/review/catalog' $auth
        $expected=if ($key -eq 'C') { 1 } else { 3 }
        if ($health.model_egress -ne 'disabled' -or $catalog.products.Count -ne $expected) { throw 'Deployment health/grants check failed.' }
    }
    try { Invoke-ReviewLocalApi '/api/v1/review/catalog' '' | Out-Null; throw 'Anonymous access unexpectedly succeeded.' }
    catch { if ($_.Exception.Message -ne 'Local review returned HTTP 401') { throw } }
    Write-Host 'Healthy: two three-product accounts, one Demo-only account; anonymous access denied; model egress disabled.'
} finally { $auth=$null; $env:PMC_REVIEW_PROXY_SECRET=$null }
