"""Real development API + Vite/Edge, using a private DB backup for test conversations."""
import hashlib
import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-port", type=int, default=8000)
    port = parser.parse_args().backend_port
    backend_url = f"http://127.0.0.1:{port}"
    for listen_port in (port,5173):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1",listen_port))
    original = ROOT / "data/facts/pmc_facts.db"
    units = ROOT / "data/facts/confirmations/inventory_units.json"
    source = json.loads(units.read_text(encoding="utf-8"))["confirmations"]
    if len(source) != 1:
        raise ValueError("Explicit approved stock source required")
    stock = ROOT / source[0]["source_uri"]
    profile = ROOT / "data/facts/confirmations/review_slim.json"
    paths = [original, stock, units, ROOT / "data/facts/confirmations/inventory_quantity_use.json", profile]
    paths += [ROOT / p for p in json.loads(profile.read_text(encoding="utf-8")).values()]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    runtime = ROOT / ".runtime" / ("workstation-acceptance-" + uuid4().hex)
    runtime.mkdir()
    snapshot = runtime / "facts.sqlite3"
    with sqlite3.connect(original.resolve().as_uri() + "?mode=ro", uri=True) as reader, sqlite3.connect(snapshot) as writer:
        reader.backup(writer)
    env = {**os.environ, "PMC_FACT_DATABASE_URL":"sqlite:///" + str(snapshot),
        "PMC_BOOK_INVENTORY_FILE":str(stock.resolve()), "PMC_REVIEW_MODE":"1", "PMC_LOCAL_REVIEW":"1", "LLM_PROVIDER":"",
        "VITE_API_BASE_URL":backend_url, "PMC_WORKSTATION_API_URL":backend_url}
    env.pop("PMC_TRIAL_MODE",None)
    processes=[]
    with (runtime/"private.log").open("w",encoding="utf-8") as log:
        try:
            for command, cwd in [([sys.executable,"-m","uvicorn","api.app:app","--host","127.0.0.1","--port",str(port),"--no-access-log"],ROOT),
                (["cmd.exe","/c","npm.cmd","run","dev"],ROOT/"pmc-agent-frontend-main/frontend")]:
                processes.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=log))
            deadline=time.monotonic()+40
            while True:
                try:
                    with urlopen(backend_url+"/health",timeout=1), urlopen("http://127.0.0.1:5173",timeout=1):
                        break
                except Exception:
                    if time.monotonic()>deadline or any(p.poll() is not None for p in processes):
                        raise RuntimeError("Private local workstation startup failed")
                    time.sleep(.2)
            def call(path, body):
                request = Request(backend_url + path,
                    data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
                with urlopen(request, timeout=30) as response:
                    return json.load(response)
            sid = call("/api/v1/agent/sessions", {"product_code":"KQ-Z112"})["session_id"]
            for quantity, sufficient in ((1, True), (2, False)):
                response = call("/api/v1/agent/query", {"message":f"生产{quantity}片可以吗",
                    "session_id":sid, "persist_session":True})
                data = response["structured_data"]["data"]
                assert len(data["materials"]) == 34 and data["synthetic"] is False
                assert data["theoretical_max_quantity"] == 1
                assert data["inventory_sufficient_for_requested"] is sufficient
            print("Current business HTTP: 34 items, maximum 1, 1 satisfies / 2 fails")
            result=subprocess.run(["cmd.exe","/c","npm.cmd","test","--","--config","playwright.workstation.config.ts"],
                cwd=ROOT/"pmc-agent-frontend-main/frontend",env=env)
            if result.returncode:
                raise RuntimeError("Actual development workstation regression failed")
            print("Real development API/browser passed with isolated conversation writes")
        finally:
            for process in reversed(processes):
                # npm's Windows command tree includes its Vite child.
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=15)
            if before != [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]:
                raise RuntimeError("Private source integrity failed")
            print("Original enterprise DB, Excel, confirmations and both dataset versions unchanged")


if __name__=="__main__":
    main()
