"""Actual persistent Agent/tool chain; synthetic SQLite, no external model access."""
import copy
from unittest.mock import patch

import pytest

from agents.planner import AgentPlanner
from tests.test_published_bom_business_confirmation import fixture
from tests.test_parent_unit_confirmation_acceptance import agent


GREETINGS = ["你好", "你好！", "您好", "嗨", "哈喽", "早上好", "晚上好",
             "hello", "HELLO", "Hello", "hi", "HI", "nihao", "NIHAO", "Ni Hao", "ni hao", "  NIHAO！  "]


@pytest.mark.parametrize("message", GREETINGS)
def test_greeting_preserves_business_context_without_tools_or_model(fixture, message):
    service, session = agent(fixture)
    service.query(session, "查询ENTERPRISE-A的BOM")
    before = copy.deepcopy(service.repository.get_session(session)["context"])
    with patch.object(service.orchestrator.registry, "resolve", side_effect=AssertionError("No business tool")), \
         patch.object(service.orchestrator.planner, "llm_factory", side_effect=AssertionError("No model")):
        response = service.query(session, message)
    assert response["intent"] == "clarification" and response["status"] == "ok"
    assert response["structured_data"]["operation"] == "conversation"
    assert service.repository.get_session(session)["context"] == before
    assert service.repository.history(session)["turns"][-1]["fact_references"] == []


@pytest.mark.parametrize("message", ["查询物料 NIHAO", "查询物料 NIHAO 库存"])
def test_explicit_greeting_named_material_is_not_greeting(fixture, message):
    service, session = agent(fixture)
    response = service.query(session, message)
    assert response["intent"] == "inventory" and response["status"] == "item_not_found"
    assert response["structured_data"]["query"]["material_code"] == "NIHAO"
    refs = service.repository.history(session)["turns"][-1]["fact_references"]
    assert refs[0]["tool_name"] == "published_inventory_query"


@pytest.mark.parametrize("message", ["有哪些已发布产品？", "提供已发布的产品", "已发布的BOM有哪些？", "已发布的bom有哪些？"])
def test_catalog_precedes_legacy_invalid_material_context(fixture, message):
    service, session = agent(fixture)
    service.query(session, "查询物料 NIHAO 库存")
    before = service.repository.get_session(session)["context"]
    response = service.query(session, message)
    assert response["intent"] == "fact_query" and response["status"] == "ok"
    assert response["structured_data"]["query"]["search_term"] is None
    assert {p["product_code"] for p in response["structured_data"]["data"]["products"]} == {"ENTERPRISE-A", "ENTERPRISE-B"}
    assert service.repository.get_session(session)["context"] == before
    refs = service.repository.history(session)["turns"][-1]["fact_references"]
    assert [r["tool_name"] for r in refs] == ["published_product_search"]


def test_overview_followup_switch_and_production_do_not_mix_objects(fixture):
    service, session = agent(fixture)
    for message in ["你好", "NIHAO", "有哪些已发布产品？"]:
        service.query(session, message)
    for message, code, count in [
        ("提供ENTERPRISE-A相关信息。", "ENTERPRISE-A", 66),
        ("那它的物料有哪些？", "ENTERPRISE-A", 66),
        ("那 ENTERPRISE-B 呢？", "ENTERPRISE-B", 91),
        ("换成ENTERPRISE-A", "ENTERPRISE-A", 66),
        ("换成ENTERPRISE-B", "ENTERPRISE-B", 91),
    ]:
        response = service.query(session, message)
        assert response["intent"] == "bom" and response["status"] == "ok"
        data = response["structured_data"]["data"]
        assert data["parent_item"]["material_code"] == code and data["line_count"] == count
        assert data["parent_item"]["unit"] == "片" and response["structured_data"]["completeness"]["price"] is False
        assert "价格" not in response["answer"] and not any(w.startswith("price_missing") for w in response["warnings"])
        refs = service.repository.history(session)["turns"][-1]["fact_references"]
        bom = next(r for r in refs if r["tool_name"] == "published_bom_query")
        assert any(w.startswith("price_missing") for w in bom["result"]["warnings"])
    response = service.query(session, "生产1片呢？")
    assert response["intent"] == "production_capacity" and response["status"] == "needs_input"
    assert response["structured_data"]["query"]["material_code"] == "ENTERPRISE-B"
    assert "生产1片" in response["answer"] and "当前不能批准" in response["answer"]
    assert "价格" not in response["answer"]
    response = service.query(session, "2026年9月16日生产1片可以吗？")
    assert response["status"] == "data_unavailable"
    assert response["structured_data"]["business_decision"]["status"] == "NOT_APPROVED"
    assert "库存不足" not in response["answer"].replace("并不代表已经确认库存不足", "")


@pytest.mark.parametrize("message", ["这个产品成本多少钱？", "采购需要多少钱？", "查询ENTERPRISE-B的完整成本"])
def test_cost_only_requests_still_refuse_missing_price_with_evidence(fixture, message):
    service, session = agent(fixture)
    service.query(session, "查询ENTERPRISE-B的BOM")
    with patch.object(service.orchestrator.registry, "resolve", side_effect=AssertionError("No speculative cost tool")):
        response = service.query(session, message)
    assert response["intent"] == "purchase_planning" and response["status"] == "data_unavailable"
    assert "缺少可靠的价格数据" in response["answer"] and "暂时无法计算完整成本" in response["answer"]
    assert response["structured_data"]["completeness"]["cost"] is False
    assert any(w.startswith("price_missing") for w in response["warnings"])
    refs = service.repository.history(session)["turns"][-1]["fact_references"]
    assert any((r["result"].get("data") or {}).get("bom_structure") for r in refs)


def test_identifiers_are_not_case_folded_or_guessed_from_suffix(fixture):
    service, session = agent(fixture)
    response = service.query(session, "查询enterprise-a的BOM")
    assert response["status"] != "ok"
    assert response["structured_data"]["query"]["material_code"] == "enterprise-a"
    plan, _ = AgentPlanner(llm_status=lambda: {"status": "warning"}).plan("3588M什么时候生效？", {})
    assert plan.entities.material_code == "3588M"  # No fabricated alias or fuzzy product.


def test_explicit_product_switch_does_not_inherit_old_task_metadata():
    context = {"active_domain": "production", "production": {
        "query_type": "production_capacity", "material_code": "ENTERPRISE-A",
        "revision": "V09", "quantity": 100, "effective_date": "2026-09-16",
        "as_of": "2026-09-11T08:30:00+08:00", "start_date": "2026-09-20",
    }}
    plan, _ = AgentPlanner(llm_status=lambda: {"status": "warning"}).plan("换成ENTERPRISE-B", context)
    assert plan.intent == "production_capacity"
    assert plan.entities.material_code == "ENTERPRISE-B"
    assert all(getattr(plan.entities, key) is None for key in
               ("revision", "quantity", "effective_date", "as_of", "start_date"))


def test_tool_failure_keeps_history_but_is_not_saved_as_new_business_object(fixture):
    service, session = agent(fixture)
    service.query(session, "查询ENTERPRISE-A的BOM")
    before = service.repository.get_session(session)["context"]
    with patch.object(service.orchestrator.registry, "resolve", side_effect=RuntimeError("synthetic internal failure")):
        response = service.query(session, "查询ENTERPRISE-B的BOM")
    assert response["status"] == "query_failed" and "synthetic internal failure" not in response["answer"]
    assert service.repository.get_session(session)["context"]["fact"] == before["fact"]
    assert len(service.repository.history(session)["turns"]) == 2
