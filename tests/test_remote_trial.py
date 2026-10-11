"""Authenticated trial only; all business facts are the existing synthetic package."""
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.trial_app import create_trial_app

SECRET = "test-only-proxy-secret-" + "x" * 32


@pytest.fixture
def trial(tmp_path, monkeypatch):
    monkeypatch.setenv("PMC_TRIAL_MODE", "1")
    app = create_trial_app(tmp_path / "trial", SECRET)
    return app, TestClient(app, raise_server_exceptions=False), tmp_path


def headers(user="alice"):
    return {"X-PMC-Proxy-Key": SECRET, "X-PMC-User": user}


def session(client, user="alice"):
    response = client.post("/api/v1/agent/sessions", json={}, headers=headers(user))
    assert response.status_code == 200
    assert response.json()["scenario_id"] == "demo_scenario_50_vs_100"
    return response.json()["session_id"]


def ask(client, sid, message, user="alice"):
    return client.post("/api/v1/agent/query", json={"message": message, "session_id": sid}, headers=headers(user))


def test_no_proxy_identity_no_access(trial):
    _, client, _ = trial
    assert client.post("/api/v1/agent/sessions", json={}).status_code == 401
    assert client.get("/health", headers={"X-PMC-User": "alice"}).status_code == 401


def test_two_users_cannot_read_or_write_each_other_history(trial):
    _, client, _ = trial
    a, b = session(client), session(client, "bob")
    assert ask(client, a, "生产50台DEMO-PMC-01").status_code == 200
    for sid, user in [(a, "bob"), (b, "alice")]:
        response = client.get(f"/api/v1/agent/sessions/{sid}", headers=headers(user))
        assert response.status_code == 404 and "owner_hash" not in response.text
        assert ask(client, sid, "查库存", user).status_code == 404
    assert client.get(f"/api/v1/agent/sessions/{a}", headers=headers()).json()["turns"]


def test_50_100_purchase_and_restart_restore(trial, monkeypatch):
    app, client, root = trial
    sid = session(client)
    with patch("config.ChatOpenAI", side_effect=AssertionError("No model client")):
        fifty = ask(client, sid, "生产50台DEMO-PMC-01").json()
        hundred = ask(client, sid, "生产100台DEMO-PMC-01").json()
        purchase = ask(client, sid, "帮我生成采购建议").json()
    assert fifty["structured_data"]["data"]["inventory_sufficient_for_requested"] is True
    assert hundred["structured_data"]["data"]["inventory_sufficient_for_requested"] is False
    assert len(purchase["structured_data"]["data"]["recommendations"]) == 4
    assert "1560.00" == purchase["structured_data"]["data"]["total_purchase_cost"]
    new = TestClient(create_trial_app(root / "trial", SECRET))
    assert len(new.get(f"/api/v1/agent/sessions/{sid}", headers=headers()).json()["turns"]) == 3
    assert new.get(f"/api/v1/agent/sessions/{sid}", headers=headers("bob")).status_code == 404


def test_trial_blocks_enterprise_store_and_model_even_with_keys(trial, monkeypatch):
    import config
    from repositories.fact_store import create_fact_store
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-not-a-key")
    assert config.get_llm_configuration_status()["status"] == "warning"
    with pytest.raises(RuntimeError):
        config.get_llm()
    with pytest.raises(RuntimeError):
        create_fact_store("sqlite:///data/facts/pmc_facts.db")


def test_private_product_cannot_escape_demo_and_legacy_routes_closed(trial):
    _, client, _ = trial
    sid = session(client)
    response = ask(client, sid, "查询PRIVATE-EXAMPLE的BOM")
    assert response.status_code == 200 and response.json()["status"] != "ok"
    assert client.post("/api/v1/chat", headers=headers(), json={"message": "你好"}).status_code == 404
    assert client.get("/docs", headers=headers()).status_code == 404


def test_csrf_and_long_message_rejected(trial):
    _, client, _ = trial
    response = client.post("/api/v1/agent/sessions", json={}, headers={**headers(), "Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert ask(client, session(client), "x" * 2001).status_code == 422


def test_parallel_users_remain_isolated(trial):
    _, client, _ = trial
    sessions = {user: session(client, user) for user in ("alice", "bob")}
    def run(user):
        return ask(client, sessions[user], "生产50台DEMO-PMC-01", user)
    with concurrent.futures.ThreadPoolExecutor(2) as executor:
        responses = list(executor.map(run, sessions))
    assert all(r.status_code == 200 for r in responses)
    for user, sid in sessions.items():
        history = client.get(f"/api/v1/agent/sessions/{sid}", headers=headers(user)).json()
        assert len(history["turns"]) == 1


def test_zero_quantity_executes_no_tool_and_preserves_last_valid_context(trial):
    app, client, _ = trial
    sid = session(client)
    assert ask(client, sid, "生产76台DEMO-PMC-01").status_code == 200
    previous = app.state.service.repository.get_session(sid)["context"]
    with patch.object(app.state.service.orchestrator.registry, "resolve", side_effect=AssertionError("Zero must not execute Tool")):
        response = ask(client, sid, "生产0台").json()
    assert response["status"] == "needs_input" and "未执行事实计算" in response["answer"]
    history = app.state.service.repository.history(sid)
    assert history["context"] == previous
    assert history["turns"][-1]["fact_references"] == []
    assert ask(client, sid, "生产1台").json()["structured_data"]["data"]["requested_quantity"] == 1


def test_config_fails_closed_without_trial_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("PMC_TRIAL_MODE", raising=False)
    with pytest.raises(RuntimeError):
        create_trial_app(tmp_path / "trial", SECRET)


def test_rate_limit_is_per_authenticated_user(trial):
    _, client, _ = trial
    for _ in range(60):
        assert client.get("/health", headers=headers()).status_code == 200
    assert client.get("/health", headers=headers()).status_code == 429
    assert client.get("/health", headers=headers("bob")).status_code == 200


def test_trial_launcher_private_path_and_external_network_guard():
    root = Path(__file__).resolve().parents[1]
    code = '''
import runpy, json
module = runpy.run_path('scripts/run_remote_trial.py')
import config
checks = []
for path in ['.env', 'data/raw/not-a-real-file.xls', 'data/facts/pmc_facts.db', 'data/normalized/not-a-real-file.json']:
    try:
        open(path, 'rb')
    except PermissionError:
        checks.append('blocked')
try:
    module['isolation']('socket.connect', (None, ('api.deepseek.com', 443)))
except PermissionError:
    checks.append('blocked')
assert config.get_llm_configuration_status()['status'] == 'warning'
print(json.dumps(checks))
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=root, text=True, capture_output=True, timeout=20, check=True)
    assert json.loads(result.stdout) == ["blocked"] * 5
