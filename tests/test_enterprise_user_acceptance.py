"""User acceptance, not implementation tests: unmet requirements deliberately FAIL.

Only DeepSeek is mocked. HTTP routing, persistence, context resolution, registered
Tools and their published-fact computations run against a temporary SQLite store.
No raw data, Demo mutations, xfail or fabricated Tool outputs are used.
"""

from __future__ import annotations

import copy
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.planner import AgentPlan
from agents.tool_registry import PRIMARY_TOOLS
from api.app import app
from api.schemas.agent import UnifiedAgentResponse
from repositories.agent_conversation_repository import AgentConversationRepository
from services.persistent_agent_service import PersistentAgentService
from tests import test_published_purchase_planning as fixtures
from tests.test_inventory_fact_import import _seed_item


@dataclass(frozen=True)
class Scenario:
    id: str
    message: str
    intent: str
    check: str
    prelude: str | None = None


PRODUCTION = "帮我看看KQ-Z112现在能不能生产100台 开工日期2026-10-20"
PURCHASE = "KQ-Z112生产100台的采购建议 开工日期2026-10-20"
STOCK = "查询MAT-001库存"
ACTUAL_TOOLS = {
    "inventory": "published_inventory_query",
    "inventory_batches": "published_inventory_batch_query",
    "bom": "published_bom_query",
    "inbound": "published_inbound_supply_query",
    "production_capacity": "published_production_capacity_query",
    "purchase_planning": "published_purchase_recommendations_query",
    "inventory_risk_analysis": "published_inventory_risk_analysis",
    "inventory_fifo": "published_inventory_fifo_plan",
}

PLANNER_CASES = [
    Scenario("P01", "帮我看看KQ-Z112现在能不能生产100台", "production_capacity", "shortage"),
    Scenario("P02", "最多能生产多少", "production_capacity", "maximum", PRODUCTION),
    Scenario("P03", "如果生产200台缺什么", "production_capacity", "quantity200", PRODUCTION),
    Scenario("P04", "为什么不能生产", "production_capacity", "reuse_evidence", PRODUCTION),
    Scenario("P05", "减少到50台还能生产吗", "production_capacity", "quantity50", PRODUCTION),
    Scenario("P06", "下周生产是否有风险", "production_capacity", "future_date", PRODUCTION),
    Scenario("P07", "生产100台KQ-Z112可以吗", "production_capacity", "shortage"),
    Scenario("P08", "生产50台KQ-Z112可以开工吗", "production_capacity", "quantity50"),
    Scenario("P09", "KQ-Z112做100台库存够吗", "production_capacity", "shortage"),
    Scenario("P10", "KQ-Z112生产一百台缺哪些料", "production_capacity", "shortage"),
    Scenario("P11", "KQ-Z112生产两百台是否齐套", "production_capacity", "quantity200"),
    Scenario("P12", "KQ-Z112目前最大生产数量是多少", "production_capacity", "maximum"),
    Scenario("P13", "哪些物料限制产量", "production_capacity", "limiting", PRODUCTION),
    Scenario("P14", "哪些物料影响生产", "production_capacity", "limiting", PRODUCTION),
    Scenario("P15", "继续分析生产75台", "production_capacity", "quantity75", PRODUCTION),
    Scenario("P16", "生产100台KQ-Z112 使用V01", "production_capacity", "explicit_version"),
    Scenario("P17", "生产100台KQ-Z112 生效日期2026-10-01", "production_capacity", "explicit_date"),
    Scenario("P18", "生产100台KQ-Z112 截至2026-10-01T00:00:00+00:00", "production_capacity", "as_of"),
    Scenario("P19", "KQ-Z112物料清单有哪些", "bom", "bom"),
    Scenario("P20", "请解释刚才的缺料原因，不要重新计算", "production_capacity", "reuse_evidence", PRODUCTION),
]

BUYER_CASES = [
    Scenario("B01", "哪些物料需要采购", "purchase_planning", "purchase", PRODUCTION),
    Scenario("B02", "帮我生成采购建议", "purchase_planning", "purchase", PRODUCTION),
    Scenario("B03", "哪个物料最紧急", "purchase_planning", "priority", PURCHASE),
    Scenario("B04", "预计采购多少钱", "purchase_planning", "cost_answer", PURCHASE),
    Scenario("B05", "帮我写采购邮件", "clarification", "email_draft", PURCHASE),
    Scenario("B06", "KQ-Z112生产100台的采购建议 开工日期2026-10-20", "purchase_planning", "purchase"),
    Scenario("B07", "KQ-Z112生产100台的采购计划 开工日期2026-10-20", "purchase_planning", "purchase"),
    Scenario("B08", "KQ-Z112生产100台的采购量 开工日期2026-10-20", "purchase_planning", "purchase"),
    Scenario("B09", "KQ-Z112生产100台的采购成本 开工日期2026-10-20", "purchase_planning", "cost_answer"),
    Scenario("B10", "采购建议保持MOQ，不要随意增加数量", "purchase_planning", "moq", PURCHASE),
    Scenario("B11", "查看刚才的采购建议", "purchase_planning", "purchase", PURCHASE),
    Scenario("B12", "减少到50台的采购建议呢", "purchase_planning", "no_purchase", PURCHASE),
    Scenario("B13", "生产200台的采购计划呢", "purchase_planning", "purchase200", PURCHASE),
    Scenario("B14", "采购建议里哪些交期长", "purchase_planning", "priority", PURCHASE),
    Scenario("B15", "采购成本合计是多少", "purchase_planning", "cost_answer", PURCHASE),
    Scenario("B16", "MAT-001采购订单什么时候到货", "inbound", "inbound"),
    Scenario("B17", "MAT-001还有多少在途", "inbound", "inbound"),
    Scenario("B18", "请把采购建议写成给供应商的邮件草稿", "purchase_planning", "email_draft", PURCHASE),
    Scenario("B19", "KQ-Z112生产100台的采购建议", "purchase_planning", "missing_start"),
    Scenario("B20", "采购计划的供应商缺失时不要推荐其他供应商", "purchase_planning", "missing_supplier", PURCHASE),
]

WAREHOUSE_CASES = [
    Scenario("W01", "现在库存有什么问题", "inventory", "risk_unavailable", STOCK),
    Scenario("W02", "哪些物料快过期", "clarification", "expiry", STOCK),
    Scenario("W03", "哪个批次应该优先使用", "inventory_batches", "fifo", STOCK),
    Scenario("W04", "哪些库存积压", "inventory", "stagnation", STOCK),
    Scenario("W05", "为什么库存不足", "inventory", "shortage_not_risk", STOCK),
    Scenario("W06", "查询MAT-001库存", "inventory", "inventory"),
    Scenario("W07", "MAT-001还有几件", "inventory", "inventory"),
    Scenario("W08", "MAT-001剩余多少", "inventory", "inventory"),
    Scenario("W09", "MAT-001存量是多少", "inventory", "inventory"),
    Scenario("W10", "1305000050101还有多少", "inventory", "alias"),
    Scenario("W11", "这个料有没有库存", "inventory", "inventory", STOCK),
    Scenario("W12", "这个物料有哪些批次", "inventory_batches", "batches", STOCK),
    Scenario("W13", "查看MAT-001库位", "inventory_batches", "batches"),
    Scenario("W14", "MAT-001批次有效期是多少", "inventory_batches", "expiry_answer"),
    Scenario("W15", "MAT-001按FIFO先用哪批", "inventory_batches", "fifo"),
    Scenario("W16", "MAT-001库存 截至2026-10-01T00:00:00+00:00", "inventory", "inventory"),
    Scenario("W17", "查MAT-002库存", "inventory", "new_material", STOCK),
    Scenario("W18", "MAT-001可用库存未知时还能用吗", "inventory", "unknown"),
    Scenario("W19", "MAT-001有没有临期库存风险", "inventory", "expiry"),
    Scenario("W20", "MAT-001安全库存是否不足", "inventory", "safety"),
]


class Harness:
    def __init__(self, fixture, client, llm):
        self.fixture, self.client, self.llm = fixture, client, llm
        self.plan = None
        self.reply = {"statement_ids": ["e0"], "closing": ""}
        self.session_id = None

    def ask(self, message, intent):
        # Explicit simulated DeepSeek output, NOT a mock of the Python parser or Tools.
        code = next((c for c in ("KQ-Z112", "MAT-001", "MAT-002", "1305000050101", "UNKNOWN-999") if c in message), None)
        quantities = re.search(r"(\d+)台", message)
        quantity = int(quantities.group(1)) if quantities else (200 if "两百台" in message else 100 if "一百台" in message else None)
        version = re.search(r"V\d+", message)
        effective = re.search(r"生效日期(\d{4}-\d{2}-\d{2})", message)
        start = re.search(r"开工日期(\d{4}-\d{2}-\d{2})", message)
        time = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+]\d{2}:\d{2}", message)
        self.plan = dict(intent=intent, entities=dict(material_code=code, quantity=quantity,
            revision=version.group() if version else None, effective_date=effective.group(1) if effective else None,
            start_date=start.group(1) if start else None, as_of=time.group() if time else None),
            required_tools=[PRIMARY_TOOLS[intent]] if intent in PRIMARY_TOOLS else [], missing_parameters=[])
        payload = dict(message=message, persist_session=True)
        if self.session_id:
            payload["session_id"] = self.session_id
        response = self.client.post("/api/v1/agent/query", json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        UnifiedAgentResponse.model_validate(result)
        self.session_id = result["session_id"]
        history = self.client.get(f"/api/v1/agent/sessions/{self.session_id}")
        assert history.status_code == 200
        self.turn = history.json()["turns"][-1]
        assert self.turn["response"] == result
        # Reference numbers and identifiers must originate in user input or saved evidence.
        permitted = json.dumps({"message": message, "query": result["structured_data"].get("query"),
            "references": self.turn["fact_references"]}, ensure_ascii=False)
        numbers = lambda text: set(re.findall(r"\d+(?:\.\d+)?", text))
        assert numbers(result["answer"]) <= numbers(permitted), "Answer introduced an ungrounded number"
        assert not any(word in result["answer"] for word in ("Traceback", "secret-test-key", "999999"))
        refs = [r for r in self.turn["fact_references"] if r["tool_name"] != "published_bom_context"]
        for reference in refs:
            assert reference["tool_name"] in ACTUAL_TOOLS.values()
            assert set(("status", "query", "data", "completeness", "provenance", "warnings")) <= reference["result"].keys()
        steps = result["structured_data"].get("completed_steps", [])
        if result["structured_data"].get("data") is not None and intent != "inbound":
            assert refs, "Successful answer lacks persisted Tool evidence"
            assert refs[-1]["result"]["data"] == result["structured_data"]["data"]
            if result["status"] == "ok":
                assert result["provenance"], "Successful facts must have provenance"
            assert steps, "Completed Tool selection must be visible"
        return result, refs, steps


@pytest.fixture
def enterprise(monkeypatch):
    for cases in (PLANNER_CASES, BUYER_CASES, WAREHOUSE_CASES):
        assert len(cases) == 20 and len({case.message for case in cases}) == 20
    assert len({case.id for case in PLANNER_CASES + BUYER_CASES + WAREHOUSE_CASES}) == 60
    fixture = fixtures.PublishedPurchasePlanningTests(methodName="test_moq_is_used_when_positive_requirement_is_smaller")
    fixture.setUp()
    try:
        fixture.items["KQ-Z112"] = _seed_item(fixture.facts, "KQ-Z112")
        fixture._bom([("MAT-001", "1"), ("MAT-002", "2")], parent="KQ-Z112")
        with fixture.store.transaction() as connection:
            fixture.store.execute(connection, "UPDATE bom_headers SET version='V01' WHERE parent_material_code='KQ-Z112'")
        fixture._inventory({"MAT-001": "75", "MAT-002": "150"}, expiry="2026-10-25")
        # Two real facts in one snapshot, distinct locations/dates. No aggregate replacement.
        with fixture.store.transaction() as connection:
            fixture.store.execute(connection, "UPDATE inventory_facts SET on_hand_qty='50', available_qty='50', location='A' WHERE raw_material_code='MAT-001'")
            fixture.store.execute(connection,
                "INSERT INTO inventory_facts (id, inventory_snapshot_id, item_id, raw_material_code, batch_no, location, on_hand_qty, available_qty, reserved_qty, received_at, expiry_date, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "SELECT ?, inventory_snapshot_id, item_id, raw_material_code, 'LOT-LATER', 'B', '25', '25', '0', '2026-09-15T00:00:00+00:00', '2027-01-01', import_batch_id, source_file_id, source_sheet, 4 FROM inventory_facts WHERE raw_material_code='MAT-001'",
                (str(uuid4()),))
            fixture.store.execute(connection,
                "INSERT INTO item_aliases (id, item_id, alias_code, alias_type, created_at) VALUES (?, ?, '1305000050101', 'explicit', ?)",
                (str(uuid4()), fixture.items["MAT-001"], fixtures.AT))
        fixture._inbound(["MAT-001", "MAT-002"])
        for code, lead in (("MAT-001", 3), ("MAT-002", 8)):
            fixture._policy(code)
            fixture._parameters(code, fixture._price(code), moq="20", multiple="10", lead=lead)
        monkeypatch.setenv("PMC_FACT_DATABASE_URL", f"sqlite:///{fixture.database.as_posix()}")
        llm = MagicMock()
        with TestClient(app) as client:
            harness = Harness(fixture, client, llm)

            def structured(schema, **kwargs):
                runnable = MagicMock()
                runnable.invoke.side_effect = lambda messages: copy.deepcopy(harness.plan if schema is AgentPlan else harness.reply)
                return runnable

            llm.with_structured_output.side_effect = structured
            with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "ok"}), \
                 patch("services.persistent_agent_service.get_llm", return_value=llm), \
                 patch("config.get_llm", side_effect=AssertionError("External API forbidden")):
                yield harness
    finally:
        fixture.doCleanups()


def prepare(enterprise, case):
    if case.prelude:
        kind = "inventory" if case.prelude == STOCK else "purchase_planning" if case.prelude == PURCHASE else "production_capacity"
        result, _, _ = enterprise.ask(case.prelude, kind)
        assert result["status"] == "ok", "Acceptance precondition failed"
    if case.check == "unknown":
        with enterprise.fixture.store.transaction() as connection:
            enterprise.fixture.store.execute(connection, "UPDATE inventory_facts SET available_qty=NULL, reserved_qty=NULL WHERE raw_material_code='MAT-001'")
    if case.check == "missing_supplier":
        with enterprise.fixture.store.transaction() as connection:
            enterprise.fixture.store.execute(connection, "UPDATE purchase_parameter_facts SET supplier_code=NULL")


@pytest.mark.parametrize("case", PLANNER_CASES + BUYER_CASES + WAREHOUSE_CASES, ids=lambda case: case.id)
def test_role_natural_language_acceptance(enterprise, case):
    prepare(enterprise, case)
    reuses_evidence = case.check in {"reuse_evidence", "limiting"}
    previous_turn = copy.deepcopy(enterprise.turn) if reuses_evidence else None
    if reuses_evidence:
        assert previous_turn["response"]["structured_data"]["completed_steps"][0]["operation"] == "production_analysis"
    invocation_guard = (patch("langchain_core.tools.BaseTool.invoke",
                              side_effect=AssertionError("Evidence-only follow-up must not invoke any Tool"))
                        if reuses_evidence else nullcontext())
    with patch.object(PersistentAgentService, "_tool", wraps=PersistentAgentService._tool) as selection, \
         invocation_guard as invocation:
        result, refs, steps = enterprise.ask(case.message, case.intent)
    assert result["intent"] == case.intent, f"{case.id}: wrong final intent for {case.message!r}"
    data = result["structured_data"].get("data")
    check = case.check
    if check in {"future_date", "missing_start"}:
        assert result["status"] == "needs_input"
        assert not refs and not steps
        assert "日期" in result["answer"]
        selection.assert_not_called()
        return
    if reuses_evidence:
        assert result["status"] == "ok", "Reason follow-up must reuse previous production evidence"
        assert not steps, "Reason-only follow-up unnecessarily recomputed facts"
        selection.assert_not_called()
        invocation.assert_not_called()
        original = next(ref for ref in previous_turn["fact_references"]
                        if ref["tool_name"] == ACTUAL_TOOLS["production_capacity"])
        assert refs == [original], "Follow-up must persist the original evidence unchanged"
        assert result["structured_data"]["data"] is None, "Historical explanation is not a new query result"
        assert result["structured_data"]["reused_result"] == original["result"]
        assert result["structured_data"]["reused_from_turn_id"] == previous_turn["response"]["turn_id"]
        assert result["provenance"] == original["result"]["provenance"]
        assert result["structured_data"]["query"] == previous_turn["response"]["structured_data"]["query"]
        assert "不是最新库存重查" in result["answer"]
        assert "缺口" in result["answer"]
        if check == "limiting":
            reused_data = original["result"]["data"]
            assert reused_data["product"] == "KQ-Z112"
            assert result["structured_data"]["query"]["revision"] == "V01"
            assert reused_data["theoretical_max_quantity"] == 75
            assert reused_data["requested_quantity"] == 100
            assert reused_data["inventory_sufficient_for_requested"] is False
            assert {r["material_code"]: r["shortage_qty"] for r in reused_data["materials"]} == {"MAT-001": "25", "MAT-002": "50"}
            assert {r["material_code"] for r in reused_data["limiting_materials"]} == {"MAT-001", "MAT-002"}
            assert all(code in result["answer"] for code in ("MAT-001", "MAT-002"))
        return
    if check == "email_draft":
        assert "草稿" in result["answer"], "Email draft capability is not connected"
        assert "已发送" not in result["answer"] and "已下单" not in result["answer"]
        assert result["provenance"], "Draft facts must cite existing procurement evidence"
        return
    if check in {"risk_unavailable", "expiry", "fifo", "stagnation", "shortage_not_risk", "safety"}:
        # Listing batches is NOT FIFO allocation; listing stock is NOT risk diagnosis.
        assert result["status"] in {"ok", "data_unavailable", "needs_input"}
        if result["status"] != "ok":
            assert any(term in result["answer"] for term in ("风险", "有效期", "FIFO", "呆滞", "安全库存", "入库日期")), "Unsupported risk request needs a specific limitation, not generic intent clarification"
        else:
            key = {"risk_unavailable": "expiry_assessments", "expiry": "expiry_assessments", "fifo": "allocations",
                   "stagnation": "stagnant_assessments", "shortage_not_risk": "shortage_qty", "safety": "safety_stock"}[check]
            assert key in (data or {}), "Requested analysis is not present; raw stock/batch listing is insufficient"
        if check in {"risk_unavailable", "stagnation", "expiry", "safety"} and refs:
            assert refs[-1]["tool_name"] == ACTUAL_TOOLS["inventory_risk_analysis"]
            assert steps == [{"operation": "inventory_risk_analysis", "status": refs[-1]["result"]["status"]}]
            assert refs[-1]["result"]["data"] == data
            assert result["provenance"] == refs[-1]["result"]["provenance"]
        return
    if check == "missing_supplier":
        assert result["status"] == "data_unavailable"
        assert refs and steps[0]["operation"] == "purchase_plan"
        assert all(r["supplier"] is None and "supplier_code" in r["missing_fields"] for r in data["recommendations"])
        assert "供应商" in result["answer"], "Missing supplier must be explained in business language"
        return
    assert result["status"] == "ok", f"{case.id}: request not fulfilled: {result['answer']}"
    assert refs and selection.called
    assert refs[-1]["tool_name"] == ACTUAL_TOOLS[case.intent]
    if case.intent in PRIMARY_TOOLS:
        assert [step["operation"] for step in steps] == [PRIMARY_TOOLS[case.intent]]
    if case.intent == "production_capacity":
        assert data["product"] == "KQ-Z112"
        assert result["structured_data"]["query"]["revision"] == "V01"
        # Existing public contract: integer whole-product capacity, Decimal material strings.
        assert data["theoretical_max_quantity"] == 75
        if check in {"shortage", "explicit_version", "explicit_date", "as_of"}:
            assert data["requested_quantity"] == 100
            assert data["inventory_sufficient_for_requested"] is False
            assert {r["material_code"]: r["shortage_qty"] for r in data["materials"]} == {"MAT-001": "25", "MAT-002": "50"}
        elif check.startswith("quantity"):
            quantity = int(check.removeprefix("quantity"))
            assert data["requested_quantity"] == quantity
            assert data["inventory_sufficient_for_requested"] is (quantity <= 75)
        if check == "limiting":
            assert {r["material_code"] for r in data["limiting_materials"]} == {"MAT-001", "MAT-002"}
    elif case.intent == "purchase_planning":
        rows = data["recommendations"]
        if check == "no_purchase":
            assert all(r["suggested_purchase_qty"] == "0" for r in rows)
        elif check == "purchase200":
            assert {r["material"]: r["suggested_purchase_qty"] for r in rows} == {"MAT-001": "130", "MAT-002": "250"}
        else:
            assert {r["material"]: r["suggested_purchase_qty"] for r in rows} == {"MAT-001": "30", "MAT-002": "50"}
            assert data["total_purchase_cost"] == "200.00"
        if check == "priority":
            assert rows[0]["material"] == "MAT-002" and rows[0]["risk_level"] == "high"
        if check == "cost_answer":
            assert data["total_purchase_cost"] in result["answer"], "Published total cost is not explained in the answer"
    elif case.intent == "inventory":
        if check == "unknown":
            assert data["available_qty"] is None and data["reserved_qty"] is None
            assert "未知" in result["answer"]
        else:
            assert data["on_hand_qty"] == ("150" if check == "new_material" else "75")
            assert data["available_qty"] == data["on_hand_qty"]
        assert "stock.xlsx" in result["answer"]
    elif case.intent == "inventory_batches":
        assert {r["batch_no"] for r in data["batches"]} == {"LOT-2", "LOT-LATER"}
        if check == "expiry_answer":
            assert "2026-10-25" in result["answer"], "Expiry is in facts but missing from final answer"
    elif case.intent == "bom":
        assert len(data["lines"]) == 2
    elif case.intent == "inbound":
        assert data["in_transit_qty"] == "0"


@pytest.mark.parametrize("case", [
    "unknown_product", "multiple_boms", "no_bom", "future_prediction", "external_risk",
], ids=lambda case: "E-" + case)
def test_exception_acceptance(enterprise, case):
    message, intent = "生产100台KQ-Z112可以吗", "production_capacity"
    if case == "unknown_product":
        message = "生产100台UNKNOWN-999可以吗"
    elif case == "multiple_boms":
        enterprise.fixture._bom([("MAT-001", "1")], parent="KQ-Z112")
        with enterprise.fixture.store.transaction() as connection:
            enterprise.fixture.store.execute(connection, "UPDATE bom_headers SET version='V02' WHERE version='V1'")
    elif case == "no_bom":
        with enterprise.fixture.store.transaction() as connection:
            enterprise.fixture.store.execute(connection, "UPDATE import_batches SET status='staged' WHERE id IN (SELECT import_batch_id FROM bom_headers)")
    elif case == "future_prediction":
        message = "预测下周KQ-Z112能生产100台吗"
    else:
        message, intent = "预测外部供应风险，政策会导致下月断供吗", "clarification"
    with patch.object(PersistentAgentService, "_tool", wraps=PersistentAgentService._tool) as selection:
        response, refs, steps = enterprise.ask(message, intent)
    assert response["intent"] == intent
    assert response["status"] in {"needs_input", "data_unavailable"}
    assert not refs and not steps
    selection.assert_not_called()
    assert not re.search(r"预计.*\d+|库存为0|应该可以生产|可能还有库存", response["answer"])
    if case == "external_risk":
        assert any(word in response["answer"] for word in ("外部", "供应风险", "来源")), "External-provider limitation not explained"


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "forged_number", "forged_tool"])
def test_deepseek_failures_do_not_invent_facts(enterprise, failure):
    original = enterprise.llm.with_structured_output.side_effect

    def structured(schema, **kwargs):
        runnable = original(schema, **kwargs)
        if failure == "timeout":
            runnable.invoke.side_effect = TimeoutError("secret-test-key")
        elif schema is AgentPlan:
            if failure == "invalid_json":
                runnable.invoke.side_effect = None
                runnable.invoke.return_value = "not JSON"
            elif failure == "forged_tool":
                runnable.invoke.side_effect = lambda messages: {**enterprise.plan, "required_tools": ["execute_sql"]}
        elif failure == "forged_number":
            runnable.invoke.side_effect = None
            runnable.invoke.return_value = {"statement_ids": ["e0"], "answer": "可以生产999999台", "closing": ""}
        return runnable

    enterprise.llm.with_structured_output.side_effect = structured
    result, refs, steps = enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    assert result["intent"] == "production_capacity" and result["status"] == "ok"
    assert result["structured_data"]["data"]["inventory_sufficient_for_requested"] is False
    assert steps[0]["operation"] == "production_analysis" and refs
    assert result["structured_data"]["parser_source"] == ("llm" if failure == "forged_number" else "rule_fallback")


def test_restarted_http_service_keeps_evidence_and_explicit_new_item(enterprise):
    first, _, _ = enterprise.ask("生产100台KQ-Z112可以吗", "production_capacity")
    sid = enterprise.session_id
    fresh = AgentConversationRepository(enterprise.fixture.store)
    assert UnifiedAgentResponse.model_validate(fresh.history(sid)["turns"][0]["response"]).model_dump(mode="json") == first
    assert any(r["tool_name"] == "published_bom_context" for r in fresh.history(sid)["turns"][0]["fact_references"])
    # Each HTTP request constructs a fresh PersistentAgentService; no memory-only context.
    reduced, _, _ = enterprise.ask("减少到50台还能生产吗", "production_capacity")
    assert reduced["structured_data"]["data"]["requested_quantity"] == 50
    stock, _, steps = enterprise.ask("查询MAT-002库存", "inventory")
    assert stock["structured_data"]["data"]["on_hand_qty"] == "150"
    assert steps[0]["operation"] == "inventory_query"


@pytest.mark.parametrize("missing", ["inventory", "inbound", "price"])
def test_missing_authoritative_facts_remain_unknown(enterprise, missing):
    fixture = enterprise.fixture
    with fixture.store.transaction() as connection:
        if missing == "inventory":
            # Only this test's temporary database; represent a source never imported.
            fixture.store.execute(connection, "DELETE FROM inventory_facts")
            fixture.store.execute(connection, "DELETE FROM inventory_snapshots")
        elif missing == "inbound":
            fixture.store.execute(connection, "DELETE FROM inbound_supply_facts")
            fixture.store.execute(connection, "DELETE FROM inbound_supply_observations")
        else:
            fixture.store.execute(connection, "UPDATE purchase_parameter_facts SET price_record_id=NULL")
    message, intent = (STOCK, "inventory") if missing == "inventory" else (
        "MAT-001在途什么时候到", "inbound") if missing == "inbound" else (PURCHASE, "purchase_planning")
    response, refs, _ = enterprise.ask(message, intent)
    assert response["intent"] == intent and response["status"] == "data_unavailable"
    assert refs[-1]["tool_name"] == ACTUAL_TOOLS[intent]
    if missing == "price":
        assert response["structured_data"]["data"]["total_purchase_cost"] is None
        assert all(row["purchase_cost"] is None for row in response["structured_data"]["data"]["recommendations"])
    else:
        data = response["structured_data"]["data"]
        # The public unavailable contract may retain a reason, but not numerical facts.
        assert data is None or set(data) <= {"reason"}
    assert "未知" in response["answer"] or "没有" in response["answer"]


def test_persisted_references_have_file_batch_snapshot_and_bom_revision(enterprise):
    _, refs, _ = enterprise.ask(PURCHASE, "purchase_planning")
    history = enterprise.client.get(f"/api/v1/agent/sessions/{enterprise.session_id}").json()
    context = next(r for r in history["turns"][0]["fact_references"] if r["tool_name"] == "published_bom_context")
    revision = next(row for row in context["result"]["data"]["resolutions"] if row["field"] == "revision")
    assert revision["value"] == "V01"
    for source in (revision["provenance"], refs[-1]["result"]["provenance"]["materials"]["MAT-001"]["inventory"]):
        assert source["source_file"] and source["import_batch_id"] and source["content_sha256"]
    assert refs[-1]["result"]["provenance"]["materials"]["MAT-001"]["inventory"]["snapshot_at"] == fixtures.AT


def test_explicit_version_survives_unique_context_resolution(enterprise):
    response, refs, _ = enterprise.ask("生产100台KQ-Z112使用V01", "production_capacity")
    assert response["intent"] == "production_capacity" and response["status"] == "ok"
    assert refs[-1]["query"]["bom_version"] == "V01"
    assert "revision" not in {row["field"] for row in response["structured_data"]["context_evidence"]}
