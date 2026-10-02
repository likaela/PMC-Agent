"""New experience requirements, with real published facts and mocked DeepSeek only.

The 75-case catalog now accepts evidence-only follow-ups and actual analysis tools.
These additional tests guard refresh, isolation, parameters and grounding boundaries.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from agents.planner import AgentPlan, AgentPlanner
from agents.tool_registry import PRIMARY_TOOLS, ToolRegistry
from api.schemas.agent import UnifiedAgentResponse
from repositories.agent_conversation_repository import AgentConversationRepository
from services.persistent_agent_service import PersistentAgentService
from services.demo_scenario_agent_service import build_demo_scenario_agent
from tests.test_enterprise_user_acceptance import enterprise


def ask(harness, message, intent, **explicit):
    harness.plan = dict(intent=intent, entities=explicit,
        required_tools=[PRIMARY_TOOLS[intent]] if intent in PRIMARY_TOOLS else [], missing_parameters=[])
    payload = dict(message=message, persist_session=True)
    if harness.session_id:
        payload["session_id"] = harness.session_id
    http = harness.client.post("/api/v1/agent/query", json=payload)
    assert http.status_code == 200, http.text
    result = http.json()
    UnifiedAgentResponse.model_validate(result)
    harness.session_id = result["session_id"]
    turn = harness.client.get(f"/api/v1/agent/sessions/{harness.session_id}").json()["turns"][-1]
    assert turn["response"] == result
    return result, turn


@pytest.mark.parametrize("message,intent", [
    ("哪些物料需要采购", "purchase_planning"), ("预计采购多少钱", "purchase_planning"),
    ("帮我买物料", "purchase_planning"), ("哪些物料需要补货", "purchase_planning"),
    ("准备下单", "purchase_planning"), ("查询采购成本", "purchase_planning"),
    ("MAT-001采购订单什么时候到货", "inbound"), ("MAT-001预计交付日期", "inbound"),
    ("MAT-001已采购多少", "inbound"), ("MAT-001运输到哪了", "inbound"),
])
def test_agent_planner_business_semantics_with_failed_deepseek(message, intent):
    planner = AgentPlanner(llm_factory=Mock(side_effect=TimeoutError("private")), llm_status=lambda: {"status": "ok"})
    plan, source = planner.plan(message, {})
    assert plan.intent == intent
    assert source in {"rule_fallback", "legacy"}
    assert plan.required_tools == ([PRIMARY_TOOLS[intent]] if intent in PRIMARY_TOOLS else [])


@pytest.mark.parametrize("message,kind,value", [("MOQ 100", "MOQ", 100), ("LT 7", "LT", 7),
    ("采购建议保持MOQ 100，不要随意增加数量", "MOQ", 100)])
def test_constraints_are_requests_not_material_or_production_quantity(message, kind, value):
    planner = AgentPlanner(llm_status=lambda: {"status": "warning"})
    plan, _ = planner.plan(message, {})
    assert plan.entities.material_code is None
    assert plan.entities.quantity is None
    assert plan.constraints[0].model_dump() == {"type": kind, "value": value}


@pytest.mark.parametrize("message", ["查询BOM", "查询LT库存", "采购建议保持MOQ", "使用V01"])
def test_unquoted_manufacturing_abbreviation_is_not_a_material(message):
    plan, _ = AgentPlanner(llm_status=lambda: {"status": "warning"}).plan(message, {})
    assert plan.entities.material_code is None


@pytest.mark.parametrize("message", ["为什么？", "为什么不能生产？", "限制在哪里？", "哪些物料影响生产？", "怎么回事？", "请解释原因，不要重新计算"])
def test_reason_follow_up_reuses_original_evidence_without_any_tool_invocation(enterprise, message):
    first, _ = enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")[:2]
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No recomputation permitted")):
        result, turn = ask(enterprise, message, "production_capacity")
    assert result["intent"] == "production_capacity" and result["status"] == "ok"
    assert result["structured_data"]["completed_steps"] == []
    assert result["structured_data"]["data"] is None  # Explanation is not a fresh query card.
    assert result["structured_data"]["reused_result"]["data"] == first["structured_data"]["data"]
    assert result["structured_data"]["reused_from_turn_id"] == first["turn_id"]
    assert "缺口" in result["answer"] and "不是最新库存重查" in result["answer"]
    assert turn["fact_references"][0]["tool_name"] == "published_production_capacity_query"
    assert result["provenance"] == {key: value for key, value in first["provenance"].items() if key != "context_resolution"}


@pytest.mark.parametrize("message", ["为什么不能生产，请重新计算", "按最新库存再查一次", "再查一次"])
def test_explicit_refresh_invokes_real_production_tool_and_uses_new_stock(enterprise, message):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE inventory_facts SET on_hand_qty='100', available_qty='100' WHERE raw_material_code='MAT-001'")
        enterprise.fixture.store.execute(connection, "UPDATE inventory_facts SET on_hand_qty='200', available_qty='200' WHERE raw_material_code='MAT-002'")
    with patch.object(PersistentAgentService, "_tool", wraps=PersistentAgentService._tool) as selection:
        result, turn = ask(enterprise, message, "production_capacity")
    assert selection.called
    assert result["intent"] == "production_capacity" and result["status"] == "ok"
    assert result["structured_data"]["data"]["inventory_sufficient_for_requested"] is True
    assert "reused_result" not in result["structured_data"]
    assert turn["fact_references"]


def test_new_material_cannot_reuse_an_old_production_answer(enterprise):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    result, _ = ask(enterprise, "为什么UNKNOWN-999不能生产100台", "production_capacity", material_code="UNKNOWN-999", quantity=100)
    assert result["status"] == "data_unavailable"
    assert "reused_result" not in result["structured_data"]


def test_inventory_shortage_question_does_not_invent_demand(enterprise):
    enterprise.ask("查询MAT-001库存", "inventory")
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No demand evidence")):
        result, _ = ask(enterprise, "为什么库存不足", "inventory")
    assert result["status"] == "needs_input" and "需求" in result["answer"]
    assert result["structured_data"]["data"] is None


def test_fifo_uses_actual_existing_tool_and_received_at_not_expiry_order(enterprise):
    # Earliest-received lot has LATER expiry: distinguish FIFO from FEFO explicitly.
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE inventory_facts SET expiry_date='2027-12-01' WHERE batch_no='LOT-2'")
        enterprise.fixture.store.execute(connection, "UPDATE inventory_facts SET expiry_date='2026-10-25' WHERE batch_no='LOT-LATER'")
    result, turn = ask(enterprise, "MAT-001按FIFO领用60件，先用哪个批次", "inventory_batches", material_code="MAT-001", quantity=60)
    assert result["status"] == "ok"
    allocations = result["structured_data"]["data"]["allocations"]
    assert [(row["batch_no"], row["allocated_qty"]) for row in allocations] == [("LOT-2", "50"), ("LOT-LATER", "10")]
    assert turn["fact_references"][0]["tool_name"] == "published_inventory_fifo_plan"
    assert "不是按有效期" in result["answer"]
    assert result["structured_data"]["data"]["simulation_only"] is True
    _, stock, _ = enterprise.ask("查询MAT-001库存", "inventory")
    assert stock[0]["result"]["data"]["on_hand_qty"] == "75"


def test_fifo_without_explicit_quantity_asks_instead_of_guessing(enterprise):
    result, turn = ask(enterprise, "MAT-001哪个批次应该优先使用", "inventory_batches", material_code="MAT-001")
    assert result["status"] == "needs_input" and "FIFO明确领用数量" in result["answer"]
    assert not turn["fact_references"]


def test_inventory_risk_uses_actual_tool_and_preserves_missing_thresholds(enterprise):
    result, turn = ask(enterprise, "MAT-001库存健康吗", "inventory", material_code="MAT-001")
    assert result["status"] == "ok"
    data = result["structured_data"]["data"]
    assert all(row["status"] == "data_unavailable" for row in data["expiry_assessments"])
    assert all(row["status"] == "data_unavailable" for row in data["stagnant_assessments"])
    assert data["safety_stock"]["safety_stock_qty"] == "0"  # Explicit fact, not fallback.
    assert "生产缺料风险需要明确生产需求" in result["answer"]
    assert turn["fact_references"][0]["tool_name"] == "published_inventory_risk_analysis"
    assert turn["fact_references"][0]["result"]["data"] == data
    assert result["provenance"]["source_file"] == "stock.xlsx"
    assert result["structured_data"]["completed_steps"] == [{"operation": "inventory_risk_analysis", "status": "ok"}]


@pytest.mark.parametrize("alias", ["inventory_risk_analysis", "inventory_risk"])
def test_risk_aliases_resolve_to_the_same_existing_store_bound_tool(enterprise, alias):
    service = PersistentAgentService(AgentConversationRepository(enterprise.fixture.store))
    service.enable_orchestrator()
    registry = service.orchestrator.registry
    assert alias in registry.names
    tool = registry.resolve(alias)
    assert tool is registry.resolve("inventory_risk_analysis")
    assert tool.name == "published_inventory_risk_analysis"
    args = registry.arguments(alias, {"material_code": "MAT-001", "as_of": "2026-10-01T00:00:00+00:00"})
    result = tool.invoke(args)
    assert result["data"]["on_hand_qty"] == "75"
    assert result["provenance"]["source_file"] == "stock.xlsx"
    plan = AgentPlan(intent="inventory", entities={"material_code": "MAT-001"},
                     required_tools=[alias], missing_parameters=[], operation="inventory_health")
    assert plan.required_tools == [alias]


@pytest.mark.parametrize("alias", ["inventory_risk_analysis", "inventory_risk"])
def test_risk_aliases_are_rejected_for_unrelated_intents_and_demo(alias):
    with pytest.raises(ValueError):
        AgentPlan(intent="purchase_planning", entities={}, required_tools=[alias], missing_parameters=[])
    with pytest.raises(ValueError):
        AgentPlan(intent="inventory", entities={}, required_tools=[alias], missing_parameters=[])
    with pytest.raises(ValueError):
        ToolRegistry.arguments(alias, {"material_code": "MAT-001"})
    demo = ToolRegistry(scope="demo_scenario_50_vs_100", resolver=lambda kind: None)
    assert alias not in demo.names
    with pytest.raises(ValueError):
        demo.resolve(alias)


def test_explicit_risk_thresholds_forward_to_existing_rules_without_becoming_items(enterprise):
    result, turn = ask(enterprise, "MAT-001库存健康吗，临期阈值30天，呆滞阈值20天", "inventory", material_code="MAT-001")
    assert result["status"] == "ok"
    assert result["structured_data"]["data"]["thresholds"] == {"expiry_warning_days": 30, "stagnant_days": 20}
    assert turn["fact_references"][0]["query"]["expiry_warning_days"] == 30
    assert turn["fact_references"][0]["query"]["stagnant_days"] == 20
    assert result["structured_data"]["data"]["expiry_assessments"][0]["status"] == "near_expiry"
    assert result["structured_data"]["data"]["stagnant_assessments"][0]["status"] == "stagnant"


@pytest.mark.parametrize("forged", [False, True])
def test_email_uses_only_purchase_evidence_and_never_sends_or_promises(enterprise, forged):
    enterprise.ask("KQ-Z112生产100台的采购建议 开工日期2026-10-20", "purchase_planning")
    if forged:
        enterprise.reply = {"statement_ids": ["e0"], "answer": "供应商SECRET供应商承诺明天到货999999件", "closing": ""}
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("Draft must use saved purchase context")):
        result, turn = ask(enterprise, "帮我写采购邮件", "clarification")
    assert result["intent"] == "clarification" and "草稿" in result["answer"]
    for fact in ("MAT-001", "MAT-002", "SUP-1", "30", "50", "25"):
        assert fact in result["answer"]
    for forbidden in ("SECRET", "999999", "明天到货", "已下单", "已发送"):
        assert forbidden not in result["answer"]
    assert "期望交付时间：待业务人员确认" in result["answer"]
    assert result["provenance"] and turn["fact_references"]
    assert result["structured_data"]["completed_steps"] == []


def test_email_without_purchase_evidence_refuses(enterprise):
    result, turn = ask(enterprise, "帮我写采购邮件", "clarification")
    assert result["status"] == "needs_input" and "请先完成采购分析" in result["answer"]
    assert not turn["fact_references"]


def test_email_does_not_reuse_an_inactive_product(enterprise):
    enterprise.ask("KQ-Z112生产100台的采购建议 开工日期2026-10-20", "purchase_planning")
    enterprise.ask("查询MAT-002库存", "inventory")
    result, _ = ask(enterprise, "帮我写采购邮件", "clarification")
    assert result["status"] == "needs_input" and "SUP-1" not in result["answer"]


def test_external_risk_explains_limit_without_provider_or_tool(enterprise):
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No external provider")):
        result, turn = ask(enterprise, "供应链风险怎么样", "clarification")
    assert result["status"] == "data_unavailable"
    assert "外部" in result["answer"] and "数据源" in result["answer"]
    assert "临期" in result["answer"] and "呆滞" in result["answer"]
    assert not turn["fact_references"]


def test_requested_moq_does_not_override_published_moq(enterprise):
    enterprise.ask("KQ-Z112生产100台的采购建议 开工日期2026-10-20", "purchase_planning")
    result, _ = ask(enterprise, "采购建议保持MOQ 100", "purchase_planning")
    assert result["status"] == "ok"
    assert result["structured_data"]["requested_constraints"] == [{"type": "MOQ", "value": 100}]
    assert {row["material"]: row["suggested_purchase_qty"] for row in result["structured_data"]["data"]["recommendations"]} == {"MAT-001": "30", "MAT-002": "50"}
    assert "已发布参数" in result["warnings"][-1]


def test_email_unknown_supplier_is_explicit_and_never_filled_by_model(enterprise):
    with enterprise.fixture.store.transaction() as connection:
        enterprise.fixture.store.execute(connection, "UPDATE purchase_parameter_facts SET supplier_code=NULL")
    result, _ = ask(enterprise, "KQ-Z112生产100台的采购建议 开工日期2026-10-20", "purchase_planning", material_code="KQ-Z112", quantity=100, start_date="2026-10-20")
    assert result["status"] == "data_unavailable"
    draft, turn = ask(enterprise, "帮我写采购邮件", "clarification")
    assert "草稿" in draft["answer"] and "供应商 未知" in draft["answer"]
    assert "SUP-1" not in draft["answer"]
    assert all(row["supplier"] is None for row in turn["fact_references"][0]["result"]["data"]["recommendations"])


def test_reason_evidence_does_not_cross_sessions(enterprise):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    enterprise.session_id = None
    result, turn = ask(enterprise, "为什么不能生产", "production_capacity")
    assert result["status"] == "needs_input"
    assert "reused_result" not in result["structured_data"]
    assert not turn["fact_references"]


def test_inventory_analysis_is_bound_to_conversation_store_not_global_database(enterprise, monkeypatch):
    service = PersistentAgentService(AgentConversationRepository(enterprise.fixture.store))
    service.enable_orchestrator()
    sid = service.repository.create_session()["session_id"]
    monkeypatch.setenv("PMC_FACT_DATABASE_URL", "sqlite:///DO-NOT-OPEN.db")
    with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"}), \
         patch("repositories.fact_store.create_fact_store", side_effect=AssertionError("Wrong data scope")):
        result = service.query(sid, "MAT-001库存健康吗")
    assert result["status"] == "ok"
    assert result["provenance"]["source_file"] == "stock.xlsx"
    assert service.repository.history(sid)["turns"][0]["fact_references"][0]["tool_name"] == "published_inventory_risk_analysis"


def test_enterprise_analysis_registry_is_not_available_in_demo(enterprise, tmp_path):
    demo = build_demo_scenario_agent(runtime_root=tmp_path)
    demo.enable_orchestrator()
    assert "inventory_risk" not in demo.orchestrator.registry.names
    assert "inventory_risk_analysis" not in demo.orchestrator.registry.names
    assert "inventory_fifo" not in demo.orchestrator.registry.names
    with pytest.raises(ValueError):
        demo.orchestrator.registry.resolve("inventory_risk")
    sid = demo.repository.create_session()["session_id"]
    result = demo.query(sid, "生产50台DEMO-PMC-01")
    assert result["structured_data"]["data"]["inventory_sufficient_for_requested"] is True
    assert result["provenance"]["scenario_id"] == "demo_scenario_50_vs_100"


def test_history_read_failure_is_sanitized_and_does_not_trigger_recalculation(enterprise):
    enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    with patch.object(AgentConversationRepository, "history", side_effect=RuntimeError("secret-test-key")), \
         patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No refresh on history failure")):
        http = enterprise.client.post("/api/v1/agent/query", json=dict(message="为什么不能生产", session_id=enterprise.session_id))
    assert http.status_code == 200
    result = http.json()
    assert result["status"] == "query_failed" and result["structured_data"]["data"] is None
    assert "secret-test-key" not in result["answer"]
    history = enterprise.client.get(f"/api/v1/agent/sessions/{enterprise.session_id}").json()
    assert not history["turns"][-1]["fact_references"]


def test_inventory_context_read_failure_is_sanitized(enterprise):
    with patch("agents.inventory_operations.InventoryOperations.prepare", side_effect=RuntimeError("secret-test-key")):
        result, turn = ask(enterprise, "MAT-001库存健康吗", "inventory", material_code="MAT-001")
    assert result["status"] == "query_failed" and result["structured_data"]["data"] is None
    assert "secret-test-key" not in result["answer"]
    assert not turn["fact_references"]
