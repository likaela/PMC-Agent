$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$savedBase = $env:VITE_API_BASE_URL
$savedTrial = $env:VITE_TRIAL_MODE
$savedDist = $env:PMC_TRIAL_BUILD_OUT
try {
    $env:VITE_API_BASE_URL = '/'
    $env:VITE_TRIAL_MODE = 'true'
    $env:PMC_TRIAL_BUILD_OUT = Join-Path $projectRoot '.runtime/remote-trial-web'
    Push-Location (Join-Path $projectRoot 'pmc-agent-frontend-main/frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Trial frontend build failed' }
    } finally { Pop-Location }
} finally {
    $env:VITE_API_BASE_URL = $savedBase
    $env:VITE_TRIAL_MODE = $savedTrial
    $env:PMC_TRIAL_BUILD_OUT = $savedDist
}
