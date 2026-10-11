"""Synthetic Excel only; real Agent chain, no model and no private DB writes."""
import copy
import hashlib
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from repositories.book_inventory_repository import BookInventoryRepository
from repositories.agent_conversation_repository import AgentConversationRepository
from repositories.fact_query_repository import FactQueryRepository
from services.fact_query_service import FactQueryService
from services.book_inventory_service import BookInventoryService
from services.persistent_agent_service import PersistentAgentService
from tests.test_published_bom_business_confirmation import fixture
from tests.test_parent_unit_confirmation_acceptance import confirm_parents


def stock_file(path, rows, unit=False):
    workbook = Workbook(); main = workbook.active; main.title = "库存表"
    main.append(["归属地", "库位", "物料代码", "名称", "批次号", "库存"] + (["单位"] if unit else []))
    for row in rows:
        main.append(row)
    other = workbook.create_sheet("电阻电容现库位")
    other.append(["物料代码", "库存"]); other.append(["UNMATCHED", 9999])
    workbook.save(path); workbook.close()


@pytest.fixture
def book(fixture, tmp_path):
    confirm_parents(fixture)
    facts = FactQueryService(FactQueryRepository(fixture[1]))
    codes = [r["child_item"]["material_code"] for r in facts.query_bom("ENTERPRISE-A", "V01")["data"]["lines"]]
    path = tmp_path / "stock.xlsx"
    stock_file(path, [["SITE", "A", codes[0], "Synthetic A", "LOT1", 5],
                      ["SITE", "B", codes[0], "Synthetic A", "LOT2", 7],
                      ["SITE", "C", codes[1], "Synthetic B", "LOT3", 0]])
    repo = BookInventoryRepository(path)
    service = BookInventoryService(facts, repo)
    agent = PersistentAgentService(AgentConversationRepository(fixture[0]), book_service=service)
    agent.enable_orchestrator()
    session = agent.repository.create_session()["session_id"]
    return service, agent, session, codes, path


def test_records_not_demo_exclusions_and_multiple_lots(book):
    service, _, _, codes, _ = book
    result = service.inventory(codes[0]); row = result["data"]["materials"][0]
    assert row["recorded_stock_qty"] == "12" and row["record_count"] == 2
    assert row["batch_count"] == row["location_count"] == 2
    assert row["available_qty"] is None and row["inventory_unit"] is None
    assert [r["provenance"]["row_number"] for r in row["details"]] == [2, 3]
    assert result["data"]["source_summary"]["excluded_sheets"] == ["电阻电容现库位"]


def test_no_record_is_not_zero_and_known_zero_preserved(book):
    service, _, _, codes, _ = book
    rows = service.analyze("ENTERPRISE-A", quantity=100)["data"]["materials"]
    by_code = {r["material_code"]: r for r in rows}
    assert by_code[codes[1]]["recorded_stock_qty"] == "0"
    assert by_code[codes[2]]["recorded_stock_qty"] is None
    assert by_code[codes[2]]["inventory_status"] == "no_record"
    assert all(r["available_qty"] is None for r in rows)


def test_demand_before_snapshot_and_unit_comparison_gate(book):
    service, _, _, _, _ = book
    result = service.analyze("ENTERPRISE-A", quantity=100, requested_unit="片")
    assert result["status"] == "ok" and result["completeness"]["demand"]
    assert len(result["data"]["materials"]) == 66
    assert result["data"]["matched_material_count"] == 2
    assert result["data"]["comparable_material_count"] == 0
    assert all(r["book_difference"] is None for r in result["data"]["materials"])
    assert result["data"]["can_start_production"] is None
    assert not result["data"]["formal_production_approved"]


def test_confirmed_source_unit_allows_decimal_book_shortage_only(book):
    service, _, _, codes, path = book
    stock_file(path, [["SITE", "A", codes[0], "Synthetic A", "LOT1", 0.25, "片"]], True)
    result = service.analyze("ENTERPRISE-A", quantity=100)
    row = next(r for r in result["data"]["materials"] if r["material_code"] == codes[0])
    from decimal import Decimal
    expected = Decimal(row["qty_per"]) * 100 - Decimal("0.25")
    assert row["book_shortage_qty"] == format(expected, "f")
    assert result["data"]["recommendations"][0]["suggested_purchase_qty"] == format(expected, "f")
    assert result["data"]["recommendations"][0]["supplier"] is None
    assert result["data"]["recommendations"][0]["purchase_cost"] is None
    assert result["data"]["can_start_production"] is None


def test_duplicates_retained_flagged_and_not_subtracted(book):
    service, _, _, codes, path = book
    row = ["SITE", "A", codes[0], "Synthetic A", "LOT1", 1, "片"]
    stock_file(path, [row, row], True)
    result = service.analyze("ENTERPRISE-A", quantity=100)
    row = result["data"]["materials"][0]
    assert row["record_count"] == 2 and row["recorded_stock_qty"] is None
    assert [r["recorded_stock_qty"] for r in row["details"]] == ["1", "1"]
    assert not row["duplicate_free"] and row["book_shortage_qty"] is None
    assert result["data"]["source_summary"]["duplicate_observation_count"] == 1


@pytest.mark.parametrize("bad", [None, -1, "bad", True])
def test_invalid_stock_preserves_row_and_unknown_total(book, bad):
    service, _, _, codes, path = book
    stock_file(path, [["SITE", "A", codes[0], "Synthetic A", "LOT1", bad]])
    row = service.inventory(codes[0])["data"]["materials"][0]
    assert row["record_found"] and row["recorded_stock_qty"] is None
    assert row["details"][0]["provenance"]["row_number"] == 2


def test_file_hash_cache_invalidation_and_copy_safety(book):
    service, _, _, codes, path = book
    first = service.inventory(codes[0]); sha = first["data"]["source_summary"]["content_sha256"]
    first["data"]["materials"][0]["details"].clear()
    assert len(service.inventory(codes[0])["data"]["materials"][0]["details"]) == 2
    stock_file(path, [["SITE", "A", codes[0], "Synthetic A", "LOT1", 22]])
    second = service.inventory(codes[0])
    assert second["data"]["source_summary"]["content_sha256"] != sha
    assert second["data"]["materials"][0]["recorded_stock_qty"] == "22"


def test_trial_cannot_read_even_warmed_cache(book, monkeypatch):
    service, _, _, codes, _ = book
    service.inventory(codes[0]); monkeypatch.setenv("PMC_TRIAL_MODE", "1")
    with pytest.raises(PermissionError):
        service.inventory(codes[0])


def test_multiround_reuses_evidence_without_model(book):
    _, agent, session, _, _ = book
    with patch.object(agent.orchestrator.planner, "llm_factory", side_effect=AssertionError("no egress")), \
         patch.object(agent.orchestrator.response_generator, "llm_factory", side_effect=AssertionError("no egress")):
        assert agent.query(session, "查询ENTERPRISE-A的BOM")["intent"] == "bom"
        result = agent.query(session, "这些材料库存有多少？")
        assert result["structured_data"]["data"]["matched_material_count"] == 2
        result = agent.query(session, "生产100片需要多少材料？")
        assert result["structured_data"]["data"]["requested_quantity"] == 100
        before = copy.deepcopy(result["structured_data"]["data"])
        with patch.object(agent.book_service, "analyze", side_effect=AssertionError("must reuse")):
            for question in ("哪些材料不够？", "差多少？", "帮我给个采购建议", "为什么这样判断？", "来源是什么？"):
                result = agent.query(session, question)
                assert result["structured_data"]["reused_from_turn_id"]
                assert result["structured_data"]["data"] == before
                assert result["provenance"]
        result = agent.query(session, "换成ENTERPRISE-B呢？")
        assert result["structured_data"]["data"]["product"] == "ENTERPRISE-B"
        assert len(result["structured_data"]["data"]["materials"]) == 91
        assert result["structured_data"]["data"]["requested_quantity"] == 100


def test_precise_source_date_not_fabricated_and_strict_service_unchanged(book):
    service, _, _, _, path = book
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = service.analyze("ENTERPRISE-A", quantity=100)
    assert result["provenance"]["inventory"][0]["rows"][0]["snapshot_at"] is None
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    from services.production_feasibility_query_service import ProductionFeasibilityQueryService
    strict = ProductionFeasibilityQueryService(service.facts).query("ENTERPRISE-A", "V01", requested_quantity=100, effective_date="2026-09-16")
    assert strict["status"] == "data_unavailable"


@pytest.mark.parametrize("quantity", [0, -1, True, "100"])
def test_invalid_demand_does_not_calculate(book, quantity):
    assert book[0].analyze("ENTERPRISE-A", quantity=quantity)["status"] == "invalid_query"


def test_explicit_other_version_not_replaced(book):
    result = book[0].analyze("ENTERPRISE-A", "V99", 100)
    assert result["status"] == "data_unavailable" and result["data"] is None


def test_incompatible_production_unit_does_not_compute_demand(book):
    result = book[0].analyze("ENTERPRISE-A", quantity=100, requested_unit="kg")
    assert not result["completeness"]["demand"]
    assert all(r["required_qty"] is None for r in result["data"]["materials"])


def test_published_bom_product_switch_does_not_revive_previous_book_product(book):
    _, agent, session, _, _ = book
    agent.query(session, "生产100片ENTERPRISE-A可以吗")
    agent.query(session, "查询ENTERPRISE-B的BOM")
    result = agent.query(session, "这些材料库存有多少")
    assert result["structured_data"]["data"]["product"] == "ENTERPRISE-B"
    assert len(result["structured_data"]["data"]["materials"]) == 91
    assert result["structured_data"]["data"]["requested_quantity"] is None


def test_single_inventory_tool_persists_actual_source_and_no_llm(book):
    _, agent, session, codes, _ = book
    response = agent.query(session, f"查询{codes[0]}库存")
    assert response["structured_data"]["data"]["materials"][0]["recorded_stock_qty"] == "12"
    references = agent.repository.history(session)["turns"][0]["fact_references"]
    assert references[0]["tool_name"] == "enterprise_book_inventory_query"
    assert references[0]["result"]["provenance"]["inventory"][0]["row_number"] == 2


def test_missing_bom_and_nearby_identifier_do_not_create_facts(book):
    service = book[0]
    for code in ("ENTERPRISE-AA", "UNKNOWN-PRODUCT"):
        result = service.analyze(code, quantity=100)
        assert result["status"] == "item_not_found" and result["data"] is None


def test_explicit_alias_uses_same_published_product_and_source(book):
    from repositories.inventory_fact_repository import InventoryFactRepository
    service, agent, session, _, _ = book
    InventoryFactRepository(service.facts.repository.fact_repository).add_item_alias("ENTERPRISE-A", "ALIAS-A")
    result = service.analyze("ALIAS-A", quantity=100)
    assert result["query"]["resolved_parent_material_code"] == "ENTERPRISE-A"
    assert result["data"]["product"] == "ENTERPRISE-A"
    response = agent.query(session, "生产100片ALIAS-A可以吗")
    assert response["structured_data"]["data"]["product"] == "ENTERPRISE-A"
