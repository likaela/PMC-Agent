"""Real local review acceptance with ephemeral credentials; never opens a tunnel.

--use-current-confirmations explicitly binds the already authorized local source.
Reports omit private quantities/materials; credentials are never printed.
"""
import argparse
import hashlib
import json
import os
import secrets
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
CADDY = ROOT / ".runtime/tools/caddy-2.11.7/caddy.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--settings", type=Path)
    source.add_argument("--use-current-confirmations", action="store_true")
    args = parser.parse_args()
    if args.settings:
        settings = json.loads(args.settings.read_text(encoding="utf-8"))
    else:
        units_path = ROOT / "data/facts/confirmations/inventory_units.json"
        units = json.loads(units_path.read_text(encoding="utf-8"))["confirmations"]
        if len(units) != 1:
            raise ValueError("Explicit source selection required")
        settings = dict(facts_path="data/facts/pmc_facts.db", inventory_path=units[0]["source_uri"],
            units_path="data/facts/confirmations/inventory_units.json",
            quantity_path="data/facts/confirmations/inventory_quantity_use.json",
            business_manifest_path=json.loads((ROOT / "data/facts/confirmations/current_business.json").read_text(encoding="utf-8"))["manifest_path"])
    if not CADDY.is_file() or not (ROOT / ".runtime/remote-review-web/index.html").is_file():
        raise RuntimeError("Build review frontend and prepare portable Caddy first")
    for port in (8020, 8090):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    paths = [(ROOT / settings[k]).resolve(strict=True) for k in ("facts_path", "inventory_path", "units_path", "quantity_path", "slim_dataset_path", "business_manifest_path") if settings.get(k)]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    all_products = ["KQ-Z112", "KQ-BHX3588M", "DEMO-PMC-01"]
    settings["users"] = {"review-a": all_products, "review-b": all_products, "demo-only": ["DEMO-PMC-01"]}
    runtime = ROOT / ".runtime/review-local-acceptance"
    runtime.mkdir(parents=True, exist_ok=True)
    settings_path = runtime / "data.local.json"
    settings_path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    password = secrets.token_urlsafe(32)
    hashed = subprocess.run([str(CADDY), "hash-password"], input=password.encode() + b"\n",
        capture_output=True, check=True).stdout.decode().strip()
    env = {**os.environ, "PMC_REVIEW_MODE": "1", "PMC_REVIEW_PROXY_SECRET": secrets.token_urlsafe(48),
        "PMC_REVIEW_SETTINGS": str(settings_path), "PMC_E2E_PASSWORD": password,
        "PMC_REVIEW_WEB_ROOT": str(ROOT / ".runtime/remote-review-web"),
        "XDG_CONFIG_HOME": str(runtime / "caddy-config"), "XDG_DATA_HOME": str(runtime / "caddy-data")}
    if settings.get("business_manifest_path"):
        env["PMC_CURRENT_DATASET_VERSION"] = json.loads((ROOT / settings["business_manifest_path"]).read_text(encoding="utf-8"))["dataset_version"]
    for key, user in (("A", "review-a"), ("B", "review-b"), ("C", "demo-only")):
        env["PMC_REVIEW_USER_" + key], env["PMC_REVIEW_HASH_" + key] = user, hashed
        env["PMC_E2E_USER_" + key] = user
        if key != "A":
            env["PMC_E2E_PASSWORD_" + key] = password
    subprocess.run([str(CADDY), "validate", "--config", "deploy/review/Caddyfile", "--adapter", "caddyfile"],
        cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    processes = []
    with (runtime / "acceptance.log").open("w", encoding="utf-8") as log:
        try:
            for command in ([sys.executable, "scripts/run_authorized_review.py"],
                [str(CADDY), "run", "--config", "deploy/review/Caddyfile", "--adapter", "caddyfile"]):
                processes.append(subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log))
            deadline = time.monotonic() + 40
            while True:
                try:
                    req = Request("http://127.0.0.1:8020/health", headers={"X-PMC-Proxy-Key": env["PMC_REVIEW_PROXY_SECRET"], "X-PMC-User": "review-a"})
                    with urlopen(req, timeout=1) as response:
                        assert json.load(response)["model_egress"] == "disabled"
                    break
                except Exception:
                    if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                        raise RuntimeError("Review startup failed; inspect the private acceptance log")
                    time.sleep(.2)
            try:
                urlopen("http://127.0.0.1:8090/api/v1/review/catalog", timeout=2)
                raise RuntimeError("Unauthenticated catalog must be rejected")
            except HTTPError as exc:
                assert exc.code == 401
            cases = []
            for spec in ("review-tests/review.spec.ts", "review-tests/product-context.spec.ts"):
                text = (ROOT / "pmc-agent-frontend-main/frontend" / spec).read_text(encoding="utf-8")
                cases.extend((spec, name) for name in re.findall(r'test\(\s*"([^"]+)"', text))
            for index, (spec, name) in enumerate(cases):
                if index:
                    processes[0].terminate()
                    processes[0].wait(timeout=15)
                    processes[0] = subprocess.Popen([sys.executable, "scripts/run_authorized_review.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            urlopen(Request("http://127.0.0.1:8020/health", headers={"X-PMC-Proxy-Key":env["PMC_REVIEW_PROXY_SECRET"], "X-PMC-User":"review-a"}), timeout=1).close()
                            break
                        except Exception:
                            if time.monotonic() >= deadline or processes[0].poll() is not None:
                                raise RuntimeError("Independent acceptance restart failed")
                            time.sleep(.2)
                # Each independent case gets a new rate window; production limits are unchanged.
                done = subprocess.run(["cmd.exe", "/c", "npm.cmd", "test", "--", "--config", "playwright.review.config.ts", spec, "--grep", re.escape(name)],
                    cwd=ROOT / "pmc-agent-frontend-main/frontend", env={**env, "PMC_REVIEW_E2E_OUTPUT":str(runtime / f"current-phase-{index}")})
                if done.returncode:
                    raise RuntimeError("Authorized review HTTP/browser acceptance failed")
            headers = {"X-PMC-Proxy-Key": env["PMC_REVIEW_PROXY_SECRET"], "X-PMC-User": "review-a", "Content-Type": "application/json"}
            def call(path, body=None):
                request = Request("http://127.0.0.1:8020" + path, headers=headers,
                    data=json.dumps(body).encode() if body is not None else None)
                with urlopen(request, timeout=30) as response:
                    return json.load(response)
            sid = call("/api/v1/agent/sessions", {"product_code": "KQ-Z112"})["session_id"]
            call("/api/v1/agent/query", {"session_id": sid, "message": "生产17片需要哪些物料"})
            processes[0].terminate()
            processes[0].wait(timeout=15)
            processes[0] = subprocess.Popen([sys.executable, "scripts/run_authorized_review.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 30
            while True:
                try:
                    call("/health")
                    break
                except Exception:
                    if time.monotonic() >= deadline or processes[0].poll() is not None:
                        raise RuntimeError("Review restart failed")
                    time.sleep(.2)
            restored = call("/api/v1/agent/sessions/" + sid)
            assert restored["review_product"] == "KQ-Z112"
            assert restored["turns"][-1]["response"]["structured_data"]["data"]["requested_quantity"] == 17
            print("History and ownership restored after a real backend process restart")
            for phase, case in enumerate(("最新精简：默认生产", "最新精简：目录指南", "最新精简：切换指南", "最新精简：Demo指南"), 1):
                # Each independent acceptance phase starts a fresh process, retaining the
                # same owner/session store. Do not weaken per-user production rate limits.
                processes[0].terminate()
                processes[0].wait(timeout=15)
                processes[0] = subprocess.Popen([sys.executable, "scripts/run_authorized_review.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        call("/health")
                        break
                    except Exception:
                        if time.monotonic() >= deadline or processes[0].poll() is not None:
                            raise RuntimeError("Acceptance restart failed")
                        time.sleep(.2)
                done = subprocess.run(["cmd.exe", "/c", "npm.cmd", "test", "--", "--config", "playwright.review.config.ts", "--grep", case],
                    cwd=ROOT / "pmc-agent-frontend-main/frontend", env={**env,
                        "PMC_REVIEW_E2E_OUTPUT":str(runtime / f"guide-phase-{phase}")})
                if done.returncode:
                    raise RuntimeError("Default filtered review acceptance failed")
            print("Authorized local review acceptance passed; no model egress or public tunnel")
            print("Per-question real HTTP evidence saved privately under .runtime/review-local-acceptance/guide-phase-*")
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if before != [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]:
                raise RuntimeError("Read-only source integrity check failed")
            print("Enterprise facts, source Excel and private confirmations unchanged; local test processes stopped")


if __name__ == "__main__":
    main()
