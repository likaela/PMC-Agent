$ErrorActionPreference = 'Stop'
$reviewRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$reviewRuntime = Join-Path $reviewRoot '.runtime/authorized-review'
$reviewVault = Join-Path $PSScriptRoot 'credentials.local.xml'
$reviewSettings = Join-Path $PSScriptRoot 'data.local.json'
$reviewCaddy = Join-Path $reviewRoot '.runtime/tools/caddy-2.11.7/caddy.exe'

function Read-ReviewJson([string]$Path) {
    try { return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json) }
    catch { throw 'Private JSON configuration could not be read. Inspect it locally; its contents are not printed.' }
}
function Invoke-ReviewLocalApi([string]$Path, [string]$Authorization) {
    # Loopback health/acceptance must never follow a machine-wide outbound proxy.
    Add-Type -AssemblyName System.Net.Http
    $handler=[Net.Http.HttpClientHandler]::new(); $handler.UseProxy=$false
    $client=[Net.Http.HttpClient]::new($handler); $client.Timeout=[TimeSpan]::FromSeconds(5)
    try {
        if ($Authorization) { $client.DefaultRequestHeaders.Add('Authorization','Basic '+$Authorization) }
        $response=$client.GetAsync('http://127.0.0.1:8090'+$Path).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200) { throw ('Local review returned HTTP '+[int]$response.StatusCode) }
        return ($response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json)
    } finally { $client.Dispose(); $handler.Dispose() }
}

function Unlock-ReviewValue([Security.SecureString]$Value) {
    return [Net.NetworkCredential]::new('', $Value).Password
}
function Import-ReviewEnvironment {
    if (!(Test-Path -LiteralPath $reviewVault) -or !(Test-Path -LiteralPath $reviewSettings)) {
        throw 'Run deploy/review/setup.ps1 locally first. Private configuration is missing.'
    }
    $vault = Import-Clixml -LiteralPath $reviewVault
    $env:PMC_REVIEW_PROXY_SECRET = Unlock-ReviewValue $vault.ProxySecret
    foreach ($key in @('A','B','C')) {
        [Environment]::SetEnvironmentVariable('PMC_REVIEW_USER_' + $key, $vault.Accounts[$key].User, 'Process')
        [Environment]::SetEnvironmentVariable('PMC_REVIEW_HASH_' + $key, $vault.Accounts[$key].Hash, 'Process')
    }
    $env:PMC_REVIEW_SETTINGS = $reviewSettings
    $env:PMC_REVIEW_WEB_ROOT = Join-Path $reviewRoot '.runtime/remote-review-web'
    $env:XDG_CONFIG_HOME = Join-Path $reviewRuntime 'caddy-config'
    $env:XDG_DATA_HOME = Join-Path $reviewRuntime 'caddy-data'
    return $vault
}
function Assert-ReviewProcess($Record) {
    $process = Get-Process -Id $Record.Id -ErrorAction SilentlyContinue
    if (!$process -or $process.StartTime.ToUniversalTime().Ticks -ne [long]$Record.StartTicks) { return $false }
    $expected = if ($Record.Kind -eq 'backend') { Join-Path $reviewRoot 'venv/Scripts/python.exe' } else { $reviewCaddy }
    if ([IO.Path]::GetFullPath($process.Path) -ne [IO.Path]::GetFullPath($expected)) {
        throw 'Process identity differs; refusing to stop an unrelated process.'
    }
    return $true
}
