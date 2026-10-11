$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$savedBase = $env:VITE_API_BASE_URL
$savedTrial = $env:VITE_TRIAL_MODE
$savedDist = $env:PMC_TRIAL_BUILD_OUT
try {
    $env:VITE_API_BASE_URL = '/'
    $env:VITE_TRIAL_MODE = 'true'
    $env:PMC_TRIAL_BUILD_OUT = Join-Path $projectRoot '.runtime/remote-trial-web'
    # Preserve old artifacts for private audit; never serve stale mixed assets.
    $output = [IO.Path]::GetFullPath($env:PMC_TRIAL_BUILD_OUT)
    $runtimePrefix = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime')) + [IO.Path]::DirectorySeparatorChar
    if (!$output.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe trial output path' }
    if (Test-Path -LiteralPath $output) {
        $backup = Join-Path $projectRoot ('.runtime/build-backups/remote-trial-web-' + [guid]::NewGuid().ToString('N'))
        $backup = [IO.Path]::GetFullPath($backup)
        if (!$backup.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe backup path' }
        New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
        Move-Item -LiteralPath $output -Destination $backup
    }
    Push-Location (Join-Path $projectRoot 'pmc-agent-frontend-main/frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Trial frontend build failed' }
    } finally { Pop-Location }
    & (Join-Path $projectRoot 'venv/Scripts/python.exe') (Join-Path $projectRoot 'scripts/audit_trial_bundle.py') --web-root $output
    if ($LASTEXITCODE -ne 0) { throw 'Trial asset privacy audit failed; do not serve this build' }
} finally {
    $env:VITE_API_BASE_URL = $savedBase
    $env:VITE_TRIAL_MODE = $savedTrial
    $env:PMC_TRIAL_BUILD_OUT = $savedDist
}
