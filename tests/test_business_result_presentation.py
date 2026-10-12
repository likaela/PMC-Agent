"""Synthetic sources, real persistent Agent/Tool/Evidence; no model egress."""
import copy
from decimal import Decimal
from unittest.mock import patch

import pytest

from agents.query_presentation import present_query
from services.book_capacity_query_service import BookCapacityQueryService
from tests.test_enterprise_book_analysis import book, stock_file
from tests.test_published_bom_business_confirmation import fixture
from tests.test_review_quantity_regression import authorize


def test_verified_zero_concludes_full_zero_without_filling_unknown(book, tmp_path):
    authorize(book, tmp_path)
    result = BookCapacityQueryService(book[0]).query("ENTERPRISE-A")
    d = result["data"]
    assert result["status"] == "ok" and d["verified_material_count"] == 2
    assert d["verified_material_capacity"] == d["theoretical_max_quantity"] == 0
    assert d["full_bom_capacity_determined"] and d["capacity_scope"] == "verified_subset"
    assert d["requested_quantity"] is None and len(d["materials"]) == 66
    assert d["materials"][2]["recorded_stock_qty"] is d["materials"][2]["verified_capacity"] is None
    assert all(r["available_qty"] is None for r in d["materials"])
    assert result["provenance"]["quantity_confirmation"]


def test_positive_partial_upper_bound_is_not_complete_capacity(book, tmp_path):
    service, _, _, codes, path = book
    per = service.facts.query_bom("ENTERPRISE-A", "V01")["data"]["lines"][0]["qty_per"]
    stock_file(path, [["SITE", "A", codes[0], "Synthetic", "LOT", str(Decimal(per)*8), "片"]], True)
    authorize(book, tmp_path)
    d = BookCapacityQueryService(service).query("ENTERPRISE-A")["data"]
    assert d["verified_material_capacity"] == 8 and d["theoretical_max_quantity"] is None
    assert d["full_bom_capacity_determined"] is False and d["limiting_materials"][0]["stock_sources"]


def test_complete_capacity_and_boundary_share_existing_comparison(book, tmp_path):
    service, _, _, _, path = book
    lines = service.facts.query_bom("ENTERPRISE-A", "V01")["data"]["lines"]
    stock_file(path, [["SITE", str(i), r["child_item"]["material_code"], "Synthetic", "LOT", str(Decimal(r["qty_per"])*2), "片"] for i,r in enumerate(lines)], True)
    authorize(book, tmp_path)
    d = BookCapacityQueryService(service).query("ENTERPRISE-A")["data"]
    assert d["capacity_scope"] == "complete" and d["theoretical_max_quantity"] == 2
    assert service.analyze("ENTERPRISE-A", quantity=2)["data"]["inventory_sufficient_for_requested"] is True
    assert service.analyze("ENTERPRISE-A", quantity=3)["data"]["inventory_sufficient_for_requested"] is False


def test_duplicate_bom_demands_merged_before_capacity(book, tmp_path):
    service, _, _, codes, path = book
    bom = service.facts.query_bom("ENTERPRISE-A", "V01")
    bom["data"]["lines"].append(copy.deepcopy(bom["data"]["lines"][0]))
    per = Decimal(bom["data"]["lines"][0]["qty_per"])
    stock_file(path, [["SITE", "A", codes[0], "Synthetic", "LOT", str(per*3), "片"]], True)
    authorize(book, tmp_path)
    with patch.object(service.facts, "query_bom", return_value=bom):
        d = BookCapacityQueryService(service).query("ENTERPRISE-A")["data"]
    assert d["verified_material_capacity"] == 1
    assert Decimal(d["materials"][0]["qty_per"]) == per*2
    assert len(d["materials"][0]["bom_line_sources"]) == 2


def test_duplicate_stock_not_summed_or_zero_filled(book, tmp_path):
    service, _, _, codes, path = book
    row = ["SITE", "A", codes[0], "Synthetic", "LOT", 100, "片"]
    stock_file(path, [row, row], True)
    authorize(book, tmp_path)
    r = BookCapacityQueryService(service).query("ENTERPRISE-A")
    assert r["status"] == "data_unavailable" and r["data"]["verified_material_capacity"] is None
    assert r["data"]["materials"][0]["recorded_stock_qty"] is None
    assert len(r["data"]["materials"][0]["details"]) == 2


def test_unconfirmed_source_cannot_establish_actual_capacity(book):
    r = BookCapacityQueryService(book[0]).query("ENTERPRISE-A")
    assert r["status"] == "data_unavailable" and r["data"]["verified_material_capacity"] is None
    assert r["data"]["materials"][0]["recorded_stock_qty"] == "12"


def test_stock_failure_retains_demand_and_real_error(book, tmp_path):
    authorize(book, tmp_path)
    with patch.object(book[0].observations, "load", side_effect=OSError("Synthetic read error")):
        r = BookCapacityQueryService(book[0]).query("ENTERPRISE-A")
    assert r["status"] == "query_failed" and len(r["data"]["materials"]) == 66
    assert all(row["required_qty"] is not None and row["recorded_stock_qty"] is None for row in r["data"]["materials"])


def test_agent_maximum_tool_reason_reuse_and_zero_safety(book, tmp_path):
    authorize(book, tmp_path)
    service, agent, session, _, _ = book
    with patch.object(agent.orchestrator, "run", side_effect=AssertionError("Must use book tool")):
        r = agent.query(session, "ENTERPRISE-A最多可以生产多少片？")
        assert r["status"] == "ok"
        assert r["structured_data"]["presentation"]["result_type"] == "maximum"
        assert r["structured_data"]["completed_steps"][0]["operation"] == "enterprise_book_capacity_query"
        refs = agent.repository.history(session)["turns"][-1]["fact_references"]
        assert refs[0]["tool_name"] == "enterprise_book_capacity_query" and refs[0]["result"]["warnings"]
        assert r["structured_data"]["presentation"]["user_warnings"] == []
        with patch.object(service, "analyze", side_effect=AssertionError("Reuse Evidence")):
            follow = agent.query(session, "哪些物料限制数量？")
            assert follow["structured_data"]["reused_from_turn_id"] == r["turn_id"]
            assert follow["structured_data"]["data"] == r["structured_data"]["data"]
        next_result = agent.query(session, "生产10片呢？")
        assert next_result["structured_data"]["data"]["requested_quantity"] == 10
        assert not next_result["structured_data"]["presentation"]["show_maximum"]
        before = agent.repository.get_session(session)["context"]
        with patch.object(service, "analyze", side_effect=AssertionError("Zero must not read stock")):
            assert agent.query(session, "生产0片")["status"] == "invalid_query"
        assert agent.repository.get_session(session)["context"] == before


@pytest.mark.parametrize("message,kind,expected", [
    ("查询BOM", "bom", "bom"), ("看看库存", "inventory", "inventory"),
    ("生产100片", "production_capacity", "production"), ("最多能生产多少", "production_capacity", "maximum"),
    ("查看来源", "production_capacity", "source"), ("有哪些产品", "product_search", "catalog"), ("采购建议", "purchase_planning", "purchase"),
])
def test_global_intent_policy_preserves_evidence(message, kind, expected):
    response = dict(intent=kind, status="ok", answer="Tool facts", structured_data=dict(query_type=kind, data={}),
        provenance={"source_file": "synthetic.json"}, warnings=["audit-only warning"])
    original = copy.deepcopy(response)
    shown = present_query(response, message)
    assert shown["structured_data"]["presentation"]["result_type"] == expected
    assert shown["structured_data"]["audit_warnings"] == response["warnings"]
    assert shown["structured_data"]["presentation"]["user_warnings"] == []
    assert response == original


def test_scoped_demo_production_and_reason_do_not_append_capacity():
    response = dict(intent="production_capacity", status="ok", answer="legacy maximum 75",
        structured_data=dict(query_type="production_capacity", operation="explain", reused_from_turn_id="saved",
            data=dict(calculation_scope="published_facts", product="EXAMPLE-DEMO", requested_quantity=100,
                theoretical_max_quantity=75, inventory_sufficient_for_requested=False,
                materials=[dict(material_code="PART-1",is_ready=False,shortage_qty="25")])),
        provenance={"source_file":"synthetic.json"},warnings=[])
    shown = present_query(response, "为什么不足？")
    assert "100" in shown["answer"] and "25" in shown["answer"] and "75" not in shown["answer"]
    assert shown["structured_data"]["data"]["theoretical_max_quantity"] == 75
    assert shown["structured_data"]["presentation"]["show_maximum"] is False
