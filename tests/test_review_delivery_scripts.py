"""Deployment-only regressions; no private configuration or business facts read."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_password_setup_uses_dpapi_and_stdin_without_windows_crlf():
    setup = (ROOT / 'deploy/review/setup.ps1').read_text(encoding='utf-8')
    assert 'Export-Clixml' in setup and 'ConvertTo-SecureString' in setup
    assert 'StandardInput.Write($Plaintext + "`n")' in setup
    assert 'StandardInput.WriteLine' not in setup and '--plaintext' not in setup
    assert 'SetAccessRuleProtection($true,$false)' in setup
    assert 'will not be overwritten' in setup

def test_stop_checks_recorded_process_identity_not_a_port_or_all_python():
    common = (ROOT / 'deploy/review/common.ps1').read_text(encoding='utf-8')
    stop = (ROOT / 'deploy/review/stop.ps1').read_text(encoding='utf-8')
    assert 'StartTicks' in common and 'process.Path' in common
    assert 'Assert-ReviewProcess $record' in stop
    assert '/PID $record.Id /T' in stop
    assert 'Get-Process python' not in stop and '/IM' not in stop

def test_review_start_and_health_do_not_start_a_public_tunnel():
    start = (ROOT / 'deploy/review/start.ps1').read_text(encoding='utf-8')
    health = (ROOT / 'deploy/review/health.ps1').read_text(encoding='utf-8')
    common = (ROOT / 'deploy/review/common.ps1').read_text(encoding='utf-8')
    assert 'cloudflared' not in start and 'tunnel --url' not in start
    assert 'WindowStyle Hidden' in start and 'GetAwaiter' in common
    assert 'http://127.0.0.1:8090' in common and 'UseProxy=$false' in common
    assert 'HTTP 401' in health and 'model_egress' in health
