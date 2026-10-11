"""Local production-browser acceptance; never starts a tunnel or uses private DBs."""
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CADDY = ROOT / ".runtime/tools/caddy-2.11.7/caddy.exe"


def main():
    if not CADDY.exists() or not (ROOT / ".runtime/remote-trial-web/index.html").exists():
        raise RuntimeError("Build trial frontend and provide the checksum-verified portable Caddy first")
    for port in (8010, 8080):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    private = ROOT / "data/facts/pmc_facts.db"
    before = hashlib.sha256(private.read_bytes()).hexdigest() if private.exists() else None
    password = secrets.token_urlsafe(32)
    # Ephemeral local test credential only, never a participant's real password.
    hashed = subprocess.run([str(CADDY), "hash-password", "--plaintext", password], text=True,
                            capture_output=True, check=True).stdout.strip()
    env = {**os.environ, "PMC_TRIAL_MODE": "1", "PMC_TRIAL_PROXY_SECRET": secrets.token_urlsafe(48),
        "PMC_TRIAL_USER_A": "trial-a", "PMC_TRIAL_USER_B": "trial-b",
        "PMC_TRIAL_HASH_A": hashed, "PMC_TRIAL_HASH_B": hashed,
        "XDG_CONFIG_HOME": str(ROOT / ".runtime/caddy-config"),
        "XDG_DATA_HOME": str(ROOT / ".runtime/caddy-data"),
        "PMC_TRIAL_WEB_ROOT": str(ROOT / ".runtime/remote-trial-web"), "PMC_E2E_PASSWORD": password}
    subprocess.run([str(CADDY), "validate", "--config", "deploy/trial/Caddyfile", "--adapter", "caddyfile"],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    processes = []
    runtime = ROOT / ".runtime/remote-trial"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "acceptance.log").open("w", encoding="utf-8") as log:
        try:
            for args in ([sys.executable, "scripts/run_remote_trial.py"],
                         [str(CADDY), "run", "--config", "deploy/trial/Caddyfile", "--adapter", "caddyfile"]):
                processes.append(subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=log))
            deadline = time.monotonic() + 30
            while True:
                try:
                    request = Request("http://127.0.0.1:8010/health", headers={"X-PMC-Proxy-Key":env["PMC_TRIAL_PROXY_SECRET"], "X-PMC-User":"trial-a"})
                    with urlopen(request, timeout=1) as response:
                        assert json.load(response)["model_egress"] == "disabled"
                    break
                except Exception:
                    if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                        raise RuntimeError("Local trial startup failed; see private acceptance log")
                    time.sleep(.2)
            completed = subprocess.run(["cmd.exe", "/c", "npm.cmd", "test", "--", "--config", "playwright.trial.config.ts"],
                cwd=ROOT / "pmc-agent-frontend-main/frontend", env=env)
            if completed.returncode:
                raise RuntimeError("Trial browser acceptance failed")
            if private.exists() and before != hashlib.sha256(private.read_bytes()).hexdigest():
                raise RuntimeError("Enterprise database changed")
            print("Local production acceptance passed; enterprise DB unchanged; LLM disabled; no tunnel created")
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
