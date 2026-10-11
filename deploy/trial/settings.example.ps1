# Copy to settings.local.ps1 (gitignored), then replace placeholders privately.
# Keep the proxy secret stable to restore prior sessions. Never commit this file's copy.
$env:PMC_TRIAL_PROXY_SECRET = 'REPLACE_WITH_PRIVATE_RANDOM_SECRET_AT_LEAST_32_CHARACTERS'
$env:PMC_TRIAL_USER_A = 'teacher'
$env:PMC_TRIAL_HASH_A = 'REPLACE_WITH_CADDY_PASSWORD_HASH'
$env:PMC_TRIAL_USER_B = 'student'
$env:PMC_TRIAL_HASH_B = 'REPLACE_WITH_DIFFERENT_CADDY_PASSWORD_HASH'
$env:PMC_TRIAL_WEB_ROOT = Join-Path $PSScriptRoot '../../.runtime/remote-trial-web'
$env:XDG_CONFIG_HOME = Join-Path $PSScriptRoot '../../.runtime/caddy-config'
$env:XDG_DATA_HOME = Join-Path $PSScriptRoot '../../.runtime/caddy-data'
