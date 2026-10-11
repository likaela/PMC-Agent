"""Real persistent Agent/Tools/SQLite; only DeepSeek is mocked by enterprise fixture."""

from unittest.mock import patch
import pytest

from agents.planner import AgentPlanner
from agents.tool_registry import ToolRegistry
from tests.test_enterprise_user_acceptance import enterprise
from tests.test_enterprise_agent_experience import ask
from tools.published_product_tools import build_published_product_search


@pytest.mark.parametrize("message", ["你好", "您好！", "介绍一下", "你是谁", "你能做什么", "谢谢"])
def test_small_talk_never_calls_business_tools(enterprise, message):
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No business tools")):
        result, turn = ask(enterprise, message, "clarification")
    assert result["status"] == "ok" and result["intent"] == "clarification"
    assert "PMC助手" in result["answer"] and "不猜测" in result["answer"]
    assert result["structured_data"]["completed_steps"] == [] and turn["fact_references"] == []


@pytest.mark.parametrize("message", ["我能生产什么", "帮我看看有哪些产品", "有哪些产品", "查看产品目录"])
def test_product_discovery_calls_only_readonly_published_tool(enterprise, message):
    result, turn = ask(enterprise, message, "clarification")
    assert result["status"] == "ok" and result["intent"] == "fact_query"
    products = result["structured_data"]["data"]["products"]
    assert any(row["product_code"] == "KQ-Z112" for row in products)
    assert all(row["published_bom_status"] == "published" for row in products)
    assert result["structured_data"]["completeness"]["production_feasibility"] is False
    assert "不是可生产清单" in result["answer"]
    assert [ref["tool_name"] for ref in turn["fact_references"]] == ["published_product_search"]
    assert result["provenance"]["bom_sources"][0]["source_file"]


def test_discovery_does_not_inherit_previous_task_or_choose_a_product(enterprise):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    before = enterprise.client.get(f"/api/v1/agent/sessions/{enterprise.session_id}").json()["context"]
    result, _ = ask(enterprise, "我能生产什么", "clarification")
    after = enterprise.client.get(f"/api/v1/agent/sessions/{enterprise.session_id}").json()["context"]
    assert result["structured_data"]["query"]["search_term"] is None and before == after
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("Reuse only")):
        reason, _ = ask(enterprise, "为什么不能生产", "production_capacity")
    assert reason["structured_data"]["reused_result"]["data"]["requested_quantity"] == 100


@pytest.mark.parametrize("message,term", [("生产某类产品", "某类"), ("帮我生产不存在的系列产品", "不存在的系列")])
def test_fuzzy_product_request_does_not_guess(enterprise, message, term):
    result, turn = ask(enterprise, message, "clarification")
    assert result["status"] == "data_unavailable"
    assert result["structured_data"]["query"]["search_term"] == term
    assert result["structured_data"]["data"] is None and "当前没有匹配" in result["answer"]
    assert turn["fact_references"][0]["tool_name"] == "published_product_search"


def test_named_product_literal_filter_and_missing_name_are_preserved(enterprise):
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE items SET name='控制器' WHERE material_code='KQ-Z112'")
    result, _ = ask(enterprise, "生产控制器产品", "clarification")
    assert result["structured_data"]["data"]["products"][0]["product_name"] == "控制器"
    assert len(result["structured_data"]["data"]["products"]) == 1
    tool = build_published_product_search(enterprise.fixture.store)
    unknown = tool.invoke({"search_term": "KQ-Z112"})
    assert unknown["data"]["products"][0]["product_code"] == "KQ-Z112"
    assert tool.invoke({"search_term": "%"})["status"] == "data_unavailable"  # literal, not wildcard
    assert tool.invoke({"search_term": "' OR 1=1 --"})["status"] == "data_unavailable"


def test_unpublished_bom_is_not_discovered(enterprise):
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE import_batches SET status='staged' WHERE id IN (SELECT import_batch_id FROM bom_headers)")
    result, _ = ask(enterprise, "有哪些产品", "clarification")
    assert result["status"] == "data_unavailable" and result["structured_data"]["data"] is None


def test_missing_quantity_guides_and_does_not_analyze_stock(enterprise):
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No calculation")):
        result, _ = ask(enterprise, "生产KQ-Z112可以吗", "production_capacity", material_code="KQ-Z112")
    assert result["status"] == "needs_input"
    assert "生产数量" in result["answer"] and "KQ-Z112" in result["answer"]
    assert "生产50台" in result["answer"] and result["structured_data"]["context_evidence"]


def test_missing_product_guides_without_tools(enterprise):
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No calculation")):
        result, _ = ask(enterprise, "生产100台可以吗", "production_capacity", quantity=100)
    assert result["status"] == "needs_input" and "100" in result["answer"]
    assert "产品编码" in result["answer"] and "有哪些产品" in result["answer"]


def test_missing_bom_guides_without_inventing_revision(enterprise):
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE import_batches SET status='staged' WHERE id IN (SELECT import_batch_id FROM bom_headers)")
    result, _ = ask(enterprise, "生产100台KQ-Z112可以吗", "production_capacity", material_code="KQ-Z112", quantity=100)
    assert result["status"] == "data_unavailable" and "已发布BOM" in result["answer"]
    assert "确认并发布" in result["answer"] and result["structured_data"]["context_resolution"]["resolutions"] == []


def test_greeting_keeps_production_context_and_evidence(enterprise):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    ask(enterprise, "你好", "clarification")
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("Reuse")):
        result, _ = ask(enterprise, "为什么不能生产", "production_capacity")
    assert result["structured_data"]["reused_result"]["data"]["requested_quantity"] == 100


def test_demo_registry_cannot_resolve_enterprise_product_tool():
    registry = ToolRegistry(scope="demo_scenario_50_vs_100", resolver=lambda kind: None)
    assert "published_product_search" not in registry.names
    with pytest.raises(ValueError):
        registry.resolve("published_product_search")
    plan, _ = AgentPlanner(enterprise_mode=False, llm_status=lambda: {"status": "warning"}).plan("我能生产什么", {})
    assert "published_product_search" not in plan.required_tools


def test_explicit_production_product_phrase_stays_on_existing_analysis(enterprise):
    result, turn = ask(enterprise, "生产100台KQ-Z112产品可以吗", "production_capacity", material_code="KQ-Z112", quantity=100)
    assert result["intent"] == "production_capacity"
    assert result["structured_data"]["data"]["requested_quantity"] == 100
    assert "published_product_search" not in [ref["tool_name"] for ref in turn["fact_references"]]
