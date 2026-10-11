"""Synthetic sources, real Agent/Tool/Service chain and read-only review boundary."""
import copy
import hashlib
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from api.review_app import create_review_app
from services.reviewer_agent_service import ReviewBinding, DEMO_PRODUCT, DEMO_SCENARIO, public_review_payload
from tests.test_published_bom_business_confirmation import fixture
from tests.test_enterprise_book_analysis import book
from tests.test_review_quantity_regression import authorize

SECRET = "synthetic-review-proxy-secret-" + "x" * 32

@pytest.fixture
def review(book, tmp_path, monkeypatch):
    monkeypatch.setenv("PMC_REVIEW_MODE", "1")
    quantity = authorize(book, tmp_path)
    monkeypatch.setattr("services.reviewer_agent_service.ENTERPRISE_PRODUCTS", ("ENTERPRISE-A", "ENTERPRISE-B"))
    source = book[4]
    facts_path = book[0].facts.repository.store.database_path
    before = hashlib.sha256(open(facts_path, "rb").read()).hexdigest()
    binding = ReviewBinding(facts_path=facts_path, inventory_path=source,
        units_path=tmp_path / "units.json", quantity_path=quantity, runtime_root=tmp_path / "review")
    users = {"a": ["ENTERPRISE-A", "ENTERPRISE-B", DEMO_PRODUCT], "b": ["ENTERPRISE-A", DEMO_PRODUCT], "guest": [DEMO_PRODUCT]}
    app = create_review_app(binding, SECRET, users)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers.update({"X-PMC-Proxy-Key": SECRET, "X-PMC-User": "a"})
        yield app, client, binding
    assert hashlib.sha256(open(facts_path, "rb").read()).hexdigest() == before

def new(client, product="ENTERPRISE-A"):
    response = client.post("/api/v1/agent/sessions", json={"product_code": product})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]

def ask(client, sid, message, **kwargs):
    return client.post("/api/v1/agent/query", json={"session_id": sid, "message": message, "persist_session": True, **kwargs})

def test_authenticated_catalog_and_materials(review):
    app, client, binding = review
    assert len(client.get("/api/v1/review/catalog").json()["products"]) == 3
    for product, count in [("ENTERPRISE-A", 66), ("ENTERPRISE-B", 91)]:
        result = client.get(f"/api/v1/review/products/{product}/materials").json()
        assert len(result["materials"]) == count
        assert all(r["unit"] == "片" and isinstance(r["qty_per"], str) for r in result["materials"])
    client.headers.clear()
    assert client.get("/api/v1/review/catalog").status_code == 401

@pytest.mark.parametrize("product,count", [("ENTERPRISE-A",66), ("ENTERPRISE-B",91)])
@pytest.mark.parametrize("quantity", [1,2,10,50,100,137])
def test_dynamic_quantity_real_tools_decimal_and_no_model(review, product, count, quantity):
    _, client, binding = review
    sid = new(client, product)
    service = binding.services[product]
    tool = Mock(wraps=service.book_queries.tools["enterprise_book_demand_analysis"])
    with patch.dict(service.book_queries.tools, {"enterprise_book_demand_analysis": tool}), \
         patch("config.get_llm", side_effect=AssertionError("No external model")):
        response = ask(client, sid, f"生产{quantity}片{product}可以吗")
        assert response.status_code == 200, response.text
        data = response.json()["structured_data"]["data"]
        assert tool.invoke.call_count == 1 and len(data["materials"]) == count
        assert data["requested_quantity"] == quantity
        assert data["source_summary"]["unit_confirmation"]["unit"] == "片"
        assert data["source_summary"]["quantity_confirmation"]["quantity_role"] == "actual_stock_for_review"
        for row in data["materials"]:
            assert Decimal(row["required_qty"]) == Decimal(row["qty_per"]) * quantity
            if row["actual_stock_qty"] is None:
                assert row["shortage_qty"] is None
            else:
                assert Decimal(row["shortage_qty"]) == max(Decimal(row["required_qty"]) - Decimal(row["actual_stock_qty"]), 0)
        assert not data["formal_production_approved"]

def test_zero_preserves_context_and_history_evidence(review):
    _, client, binding = review
    sid = new(client)
    assert ask(client, sid, "生产100片").status_code == 200
    repo = binding.repository
    before = copy.deepcopy(repo.get_session(sid)["context"])
    with patch.object(binding.services["ENTERPRISE-A"].book_service.observations, "load", side_effect=AssertionError("0 must not read stock")):
        response = ask(client, sid, "生产0片")
    assert response.json()["status"] == "invalid_query"
    assert repo.get_session(sid)["context"] == before
    assert repo.history(sid)["turns"][-1]["fact_references"] == []
    assert ask(client, sid, "那生产1个呢").json()["structured_data"]["data"]["requested_quantity"] == 1

def test_account_product_history_scope_and_parameter_spoofing(review):
    _, client, _ = review
    sid = new(client)
    assert ask(client, sid, "查询ENTERPRISE-A的BOM").status_code == 200
    client.headers["X-PMC-User"] = "b"
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 404
    assert ask(client, sid, "继续").status_code == 404
    assert client.post("/api/v1/agent/sessions", json={"product_code": "ENTERPRISE-B"}).status_code == 404
    client.headers["X-PMC-User"] = "guest"
    assert [p["product_code"] for p in client.get("/api/v1/review/catalog").json()["products"]] == [DEMO_PRODUCT]
    assert client.get("/api/v1/review/products/ENTERPRISE-A/materials").status_code == 404
    ds = new(client, DEMO_PRODUCT)
    assert ask(client, ds, "查询ENTERPRISE-A的BOM", scenario_id=DEMO_SCENARIO).status_code == 404
    assert ask(client, ds, "继续", scenario_id="kq_z112_review_slim").status_code == 422

def test_private_sources_redacted_current_and_history(review):
    _, client, binding = review
    sid = new(client)
    result = ask(client, sid, "生产10片，需要哪些物料").json()
    history = client.get(f"/api/v1/agent/sessions/{sid}").json()
    import json
    for payload in (result, history):
        text = json.dumps(payload)
        assert "content_sha256" not in text and "source_uri" not in text and "confirmed_by" not in text
        assert "stock.xlsx" not in text and "human_user_request" not in text
    assert history["turns"][0]["fact_references"]

def test_inventory_failure_retains_demand_and_recovers(review):
    _, client, binding = review
    sid = new(client)
    with patch.object(binding.services["ENTERPRISE-A"].book_service.observations, "load", side_effect=OSError("private path must not leak")):
        result = ask(client, sid, "生产17片").json()
    assert result["status"] == "query_failed"
    assert len(result["structured_data"]["data"]["materials"]) == 66
    assert all(Decimal(r["required_qty"]) == Decimal(r["qty_per"]) * 17 for r in result["structured_data"]["data"]["materials"])
    assert "private path" not in str(result)
    assert ask(client, sid, "生产1片").json()["status"] == "ok"

def test_readonly_fact_store_and_unknown_material_guard(review):
    _, client, binding = review
    with pytest.raises(Exception):
        with binding.fact_store.transaction() as connection:
            connection.execute("DELETE FROM bom_headers")
    sid = new(client)
    assert ask(client, sid, "查询DO-NOT-PUBLISH库存").status_code == 404
    assert ask(client, sid, "读取data/raw/private.xlsx").status_code == 422
    for path in ("/api/v1/chat", "/api/v1/workflows", "/api/v1/facts", "/data/raw/a.xls", "/.env", "/docs"):
        assert client.get(path).status_code == 404

def test_demo_existing_capacity_and_purchase_preserved(review):
    _, client, _ = review
    sid = new(client, DEMO_PRODUCT)
    for quantity, sufficient in ((50,True),(75,True),(76,False),(100,False)):
        data = ask(client, sid, f"生产{quantity}台").json()["structured_data"]["data"]
        assert data["theoretical_max_quantity"] == 75 and data["inventory_sufficient_for_requested"] is sufficient
    result = ask(client, sid, "帮我生成采购建议").json()
    assert len(result["structured_data"]["data"]["recommendations"]) == 4


def test_source_disclosure_is_not_changed_business_facts():
    result = public_review_payload({"answer": "来源：Private Company Book 01.xlsx；数量12，缺口3",
        "provenance": {"source_file": "Private Company Book 01.xlsx", "evidence_uri": "file:///private",
            "evidence_sha256": "a" * 64, "id": "private-row", "confirmed_by": "private-person"},
        "data": {"on_hand_qty": "12", "available_qty": None, "shortage_qty": "3", "approved": False}})
    assert "Private Company" not in str(result) and "private-person" not in str(result)
    assert result["data"] == {"on_hand_qty": "12", "available_qty": None, "shortage_qty": "3", "approved": False}


def test_csrf_user_spoof_and_grant_revocation(review):
    app, client, binding = review
    sid = new(client)
    assert ask(client, sid, "生产1片", ).status_code == 200
    assert client.post("/api/v1/agent/query", json={"session_id": sid, "message": "生产1片"},
        headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    client.headers["X-PMC-Proxy-Key"] = "invalid"
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 401


def test_existing_nonreview_runtime_store_is_rejected(review, tmp_path, monkeypatch):
    import sqlite3
    runtime = tmp_path / "unsafe"
    runtime.mkdir()
    with sqlite3.connect(runtime / "sessions.sqlite3") as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
    _, _, binding = review
    with pytest.raises(ValueError, match="not an authorized review"):
        ReviewBinding(facts_path=binding.fact_store.database_path, inventory_path=tmp_path / "unused",
            units_path=tmp_path / "unused", quantity_path=tmp_path / "unused", runtime_root=runtime)


def test_review_disables_unapproved_model_even_with_provider_configured(review, monkeypatch):
    import config
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-not-a-real-key")
    assert config.get_llm_configuration_status()["provider"] == "disabled"
    with pytest.raises(RuntimeError, match="egress is disabled"):
        config.get_llm()


def test_history_grants_are_rechecked_not_only_checked_at_creation(review):
    _, client, binding = review
    sid = new(client)
    assert ask(client, sid, "生产1片").status_code == 200
    # Same store, same owner secret; remove this account's enterprise disclosure grant.
    restricted = create_review_app(binding, SECRET, {"a": [DEMO_PRODUCT]})
    with TestClient(restricted) as access:
        access.headers.update({"X-PMC-Proxy-Key": SECRET, "X-PMC-User": "a"})
        assert access.get(f"/api/v1/agent/sessions/{sid}").status_code == 404
        assert access.post("/api/v1/agent/query", json={"session_id": sid, "message": "继续"}).status_code == 404


def test_demo_full_material_catalog_is_published_not_fixture_text(review):
    _, client, _ = review
    materials = client.get(f"/api/v1/review/products/{DEMO_PRODUCT}/materials").json()["materials"]
    assert {r["material_code"] for r in materials} == {"DEMO-MODULE-01", "DEMO-BOARD-01", "DEMO-CHIP-01", "DEMO-MOTOR-01", "DEMO-SCREW-01"}
    assert len(materials) == 5


@pytest.mark.parametrize("message", ["这些数量来自哪里？", "这些需求来自哪里？"])
def test_source_followup_reuses_existing_evidence_without_new_stock_read(review, message):
    _, client, binding = review
    sid = new(client)
    first = ask(client, sid, "生产17片需要哪些物料").json()
    with patch.object(binding.services["ENTERPRISE-A"].book_service.observations, "load", side_effect=AssertionError("Reuse only")):
        reply = ask(client, sid, message).json()
    assert reply["status"] == "ok"
    assert reply["structured_data"]["data"] == first["structured_data"]["data"]
    assert reply["provenance"] and reply["structured_data"]["operation"] == "explain"


@pytest.mark.parametrize("date", ["2026年9月16日", "2026-09-16"])
def test_review_date_is_not_misclassified_as_unauthorized_material(review, date):
    _, client, _ = review
    sid = new(client)
    response = ask(client, sid, f"{date}最多能生产多少片")
    assert response.status_code == 200
    assert response.json()["status"] == "data_unavailable"
