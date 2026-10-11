$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$savedReview = $env:PMC_REVIEW_BUILD_OUT
$savedTrial = $env:PMC_TRIAL_BUILD_OUT
try {
    $env:PMC_TRIAL_BUILD_OUT = $null
    $output = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime/remote-review-web'))
    $prefix = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime')) + [IO.Path]::DirectorySeparatorChar
    if (!$output.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe review output path' }
    if (Test-Path -LiteralPath $output) {
        $backup = [IO.Path]::GetFullPath((Join-Path $projectRoot ('.runtime/build-backups/remote-review-web-' + [guid]::NewGuid().ToString('N'))))
        if (!$backup.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe backup path' }
        New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
        Move-Item -LiteralPath $output -Destination $backup
    }
    $env:PMC_REVIEW_BUILD_OUT = $output
    Push-Location (Join-Path $projectRoot 'pmc-agent-frontend-main/frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Review build failed' }
    } finally { Pop-Location }
    & (Join-Path $projectRoot 'venv/Scripts/python.exe') (Join-Path $projectRoot 'scripts/audit_trial_bundle.py') --web-root $output --entry review
    if ($LASTEXITCODE -ne 0) { throw 'Review static privacy audit failed' }
} finally {
    $env:PMC_REVIEW_BUILD_OUT = $savedReview
    $env:PMC_TRIAL_BUILD_OUT = $savedTrial
}
