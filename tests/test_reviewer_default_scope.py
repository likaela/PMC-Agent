"""Default filtered scope, real tools, catalog evidence and versioned owner bindings."""
import copy
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from services.reviewer_agent_service import ReviewBinding, DEMO_PRODUCT
from tests.test_authorized_review import SECRET, new, ask
from tests.test_slim_review_scenario import selected
from tests.test_enterprise_book_analysis import book
from tests.test_published_bom_business_confirmation import fixture
from tests.test_review_quantity_regression import authorize


@pytest.fixture
def filtered(book, selected, tmp_path, monkeypatch):
    monkeypatch.setenv("PMC_REVIEW_MODE", "1")
    monkeypatch.setattr("services.reviewer_agent_service.ENTERPRISE_PRODUCTS", ("ENTERPRISE-A", "ENTERPRISE-B"))
    dataset = copy.deepcopy(selected)
    dataset["dataset_version"] = "approved-real-version"
    path = tmp_path / "filtered.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    binding = ReviewBinding(facts_path=book[0].facts.repository.store.database_path, inventory_path=book[4],
        units_path=tmp_path / "units.json", quantity_path=authorize(book, tmp_path), runtime_root=tmp_path / "review",
        slim_dataset_path=path)
    from api.review_app import create_review_app
    users = {"a": ["ENTERPRISE-A", "ENTERPRISE-B", DEMO_PRODUCT], "b": [DEMO_PRODUCT]}
    with TestClient(create_review_app(binding, SECRET, users), raise_server_exceptions=False) as client:
        client.headers.update({"X-PMC-Proxy-Key": SECRET, "X-PMC-User": "a"})
        yield binding, client


def test_default_scope_executes_filtered_tool_and_full_still_available(filtered):
    binding, client = filtered
    catalog = client.get("/api/v1/review/catalog").json()["products"]
    assert catalog[0]["default_mode"] == "slim" and len(catalog[0]["modes"]) == 2
    sid = new(client)
    tool = binding.slim.book_queries.tools["enterprise_book_demand_analysis"]
    with patch.object(type(tool), "invoke", wraps=tool.invoke) as spy:
        response = ask(client, sid, "生产1件").json()
    assert spy.call_count == 1
    data = response["structured_data"]["data"]
    assert data["slim_review"] and len(data["materials"]) == binding.slim.book_service.dataset["retained_material_count"]
    assert data["inventory_sufficient_for_requested"] and not data["synthetic"]
    assert data["dataset_version"] == "approved-real-version" and response["review_mode"] == "slim"
    assert client.get("/api/v1/review/products/ENTERPRISE-A/materials").json()["analysis_mode"] == "slim"
    full = client.post("/api/v1/agent/sessions", json={"product_code": "ENTERPRISE-A", "analysis_mode": "full"}).json()
    assert full["scenario_id"] is None
    assert ask(client, full["session_id"], "查询ENTERPRISE-A的BOM").json()["structured_data"]["data"]["line_count"] == 66
    assert ask(client, sid, "查看完整企业BOM").status_code == 409


def test_invalid_zero_reuse_history_and_ambiguous_addition(filtered):
    binding, client = filtered
    sid = new(client)
    first = ask(client, sid, "生产1片").json()
    context = copy.deepcopy(binding.slim.repository.get_session(sid)["context"])
    with patch.object(binding.slim.book_service.observations, "load", side_effect=AssertionError("Must not execute")):
        assert ask(client, sid, "生产0片").json()["status"] == "invalid_query"
        why = ask(client, sid, "为什么不能生产？").json()
    assert why["structured_data"]["data"] == first["structured_data"]["data"]
    assert binding.slim.repository.get_session(sid)["context"] == context
    assert ask(client, sid, "再生产1件呢").json()["status"] == "needs_input"
    assert ask(client, sid, "那生产1个呢").json()["structured_data"]["data"]["requested_quantity"] == 1
    history = client.get(f"/api/v1/agent/sessions/{sid}").json()
    assert history["review_mode"] == "slim" and history["dataset_version"] == "approved-real-version"
    assert history["turns"][1]["fact_references"] == []
    assert "dataset_sha256" not in json.dumps(history)


@pytest.mark.parametrize("message,expected", [("有哪些产品？",3),("查询已发布BOM的产品",3),
    ("有哪些可以查询的BOM产品？",3),("给我看看产品目录",3),("能查询哪些产品",3),
    ("查询可以使用的产品",3),("有哪些Demo产品？",1),("只查看正式发布的企业BOM产品",2),
    ("只显示正式企业已发布BOM",2),("只查询企业正式已发布的BOM",2)])
def test_catalog_queries_are_authorized_and_not_enterprise_demo_facts(filtered, message, expected):
    binding, client = filtered
    sid = new(client)
    result = ask(client, sid, message).json()
    assert result["status"] == "ok", result
    products = result["structured_data"]["data"]["products"]
    assert len(products) == expected
    if any(p["product_code"] == DEMO_PRODUCT for p in products):
        assert next(p for p in products if p["product_code"] == DEMO_PRODUCT)["published_bom_status"] == "synthetic"
    history = client.get(f"/api/v1/agent/sessions/{sid}").json()
    assert history["turns"][0]["fact_references"][0]["tool_name"] == "published_product_search"
    client.headers["X-PMC-User"] = "b"
    demo = new(client, DEMO_PRODUCT)
    assert len(ask(client, demo, "有哪些产品？").json()["structured_data"]["data"]["products"]) == 1
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 404


def test_material_alias_query_is_bound_to_retained_set(filtered):
    binding, client = filtered
    rows = client.get("/api/v1/review/products/ENTERPRISE-A/materials").json()["materials"]
    sid = new(client)
    result = ask(client, sid, f"查询{rows[0]['material_code']}库存").json()
    assert len(result["structured_data"]["data"]["materials"]) == 1
    assert result["structured_data"]["data"]["materials"][0]["recorded_stock_qty"] == rows[0]["stock_qty"]
    retained = {r["material_code"] for r in rows}
    excluded = next(a for a in binding.slim.book_queries.presentation.aliases.values() if a not in retained)
    assert ask(client, sid, f"查询{excluded}库存").status_code == 404


@pytest.mark.parametrize("message", ["为什么不能生产1片？", "限制在哪里？", "哪些物料影响生产？"])
def test_explanation_with_matching_quantity_reuses_existing_evidence(filtered, message):
    binding, client = filtered
    sid = new(client)
    first = ask(client, sid, "生产1片").json()
    with patch.object(binding.slim.book_service.observations, "load", side_effect=AssertionError("Do not recalculate")):
        result = ask(client, sid, message).json()
    assert result["structured_data"]["data"] == first["structured_data"]["data"]
    assert result["structured_data"]["reused_from_turn_id"] == first["turn_id"]
    assert result["structured_data"]["completed_steps"] == []


def test_different_quantity_or_explicit_refresh_still_calls_tool(filtered):
    binding, client = filtered
    sid = new(client)
    ask(client, sid, "生产1片")
    tool = binding.slim.book_queries.tools["enterprise_book_demand_analysis"]
    for message in ("为什么不能生产2片？", "按最新库存再查一次为什么不能生产2片？"):
        with patch.object(type(tool), "invoke", wraps=tool.invoke) as spy:
            result = ask(client, sid, message).json()
        assert spy.call_count == 1
        assert result["structured_data"]["data"]["requested_quantity"] == 2
        assert "reused_from_turn_id" not in result["structured_data"]


def test_scope_and_dataset_spoofing_cannot_reinterpret_sessions(filtered):
    binding, client = filtered
    sid = new(client)
    assert ask(client, sid, "生产1片", scenario_id="demo_scenario_50_vs_100").status_code == 422
    assert ask(client, sid, "查询ENTERPRISE-B的BOM").status_code == 409
    binding.slim.repository.dataset["dataset_sha256"] = "different-version"
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 404


def test_bare_demo_overview_and_full_material_synonym_keep_original_history(filtered):
    _, client = filtered
    demo = new(client, DEMO_PRODUCT)
    result = ask(client, demo, "查询DEMO-PMC-01。").json()
    assert result["status"] == "ok" and result["structured_data"]["data"]["line_count"] == 3
    history = client.get(f"/api/v1/agent/sessions/{demo}").json()
    assert history["turns"][0]["user_query"] == "查询DEMO-PMC-01。"
    full = client.post("/api/v1/agent/sessions", json={"product_code":"ENTERPRISE-A", "analysis_mode":"full"}).json()
    assert ask(client, full["session_id"], "查询ENTERPRISE-A完整物料").json()["structured_data"]["data"]["line_count"] == 66
    assert ask(client, full["session_id"], "查询这个产品的BOM").json()["structured_data"]["data"]["line_count"] == 66
