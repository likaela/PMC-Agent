"""Synthetic workbook, real persistent Agent/Tool chain; no private LLM egress."""
import copy
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from repositories.book_inventory_repository import BookInventoryRepository
from repositories.inventory_unit_confirmation_repository import (
    InventoryQuantityConfirmationRepository, InventoryUnitConfirmationRepository)
from tests.test_enterprise_book_analysis import book, stock_file
from tests.test_published_bom_business_confirmation import fixture


def authorize(book, tmp_path, **changes):
    service, _, _, _, source = book
    event = dict(source_uri=str(source), source_file=source.name,
        content_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), sheet_name="库存表",
        quantity_field="库存", unit="片", confirmed_by="Synthetic reviewer",
        reason="Synthetic review quantity authorization only", recorded_at="2026-10-10T00:00:00+08:00",
        user_statement="This vetted source quantity is actual stock for review comparison",
        applies_to_existing_source_only=True, quantity_role="actual_stock_for_review",
        product_scope=[dict(product="ENTERPRISE-A", revision="V01"), dict(product="ENTERPRISE-B", revision="V01")])
    event.update(changes)
    path = tmp_path / "quantity.json"
    path.write_text(json.dumps(dict(confirmations=[event]), ensure_ascii=False), encoding="utf-8")
    unit_path = tmp_path / "units.json"
    unit_path.write_text(json.dumps(dict(confirmations=[{k: v for k,v in event.items()
        if k not in {"quantity_role", "product_scope"}}]), ensure_ascii=False), encoding="utf-8")
    service.observations = BookInventoryRepository(source,
        unit_confirmations=InventoryUnitConfirmationRepository(unit_path),
        quantity_confirmations=InventoryQuantityConfirmationRepository(path))
    return path


def test_100_50_zero_1_preserves_context_and_current_evidence(book, tmp_path):
    authorize(book, tmp_path)
    service, agent, session, _, _ = book
    for message, quantity in [("生产100片ENTERPRISE-A",100), ("生产50个呢",50)]:
        result = agent.query(session, message)
        data = result["structured_data"]["data"]
        assert data["requested_quantity"] == quantity
        assert len(data["materials"]) == 66 and all(r["required_qty"] is not None for r in data["materials"])
    context = copy.deepcopy(agent.repository.get_session(session)["context"])
    with patch.object(service.observations, "load", side_effect=AssertionError("Invalid quantity must not read stock")), \
         patch.object(agent.orchestrator, "run", side_effect=AssertionError("No business Tool")):
        for invalid in ("生产0个", "生产0片", "生产零个", "生产-1片", "生产-1", "生产负数", "生产1.5片", "生产1.5", "生产1e3片", "生产abc个", "生产1/2片"):
            result = agent.query(session, invalid)
            assert result["status"] == "invalid_query" and "大于0" in result["answer"]
            assert "ENTERPRISE-A" in result["answer"]
            assert result["structured_data"]["data"] is None
            assert agent.repository.get_session(session)["context"] == context
            assert agent.repository.history(session)["turns"][-1]["fact_references"] == []
    result = agent.query(session, "生产1个")
    data = result["structured_data"]["data"]
    assert data["requested_quantity"] == 1 and data["product_unit"] == "片"
    assert data["product"] == "ENTERPRISE-A"
    assert agent.repository.history(session)["turns"][-1]["response"]["structured_data"]["data"] == data
    recovered = agent.repository.get_session(session)["context"]
    assert recovered["production"]["quantity"] == 1


@pytest.mark.parametrize("product,count", [("ENTERPRISE-A",66),("ENTERPRISE-B",91)])
@pytest.mark.parametrize("quantity", [1,50,100])
def test_all_bom_demands_decimal_independent_of_inventory(book,tmp_path,product,count,quantity):
    authorize(book,tmp_path)
    data = book[0].analyze(product, quantity=quantity, requested_unit="个")["data"]
    assert len(data["materials"]) == count
    for row in data["materials"]:
        assert Decimal(row["required_qty"]) == Decimal(row["qty_per"]) * quantity
        assert row["available_qty"] is None and row["reserved_qty"] is None


def test_inventory_io_failure_preserves_bom_demands_and_recovers(book,tmp_path,caplog):
    authorize(book,tmp_path)
    service,agent,session,_,_ = book
    with patch.object(service.observations,"load",side_effect=OSError("Synthetic I/O diagnostic")):
        result = agent.query(session,"生产50个ENTERPRISE-A")
    assert result["status"] == "query_failed"
    data=result["structured_data"]["data"]
    assert len(data["materials"]) == 66 and all(r["required_qty"] is not None for r in data["materials"])
    assert all(r["recorded_stock_qty"] is None for r in data["materials"])
    assert "Synthetic I/O diagnostic" in caplog.text and "Synthetic I/O diagnostic" not in result["answer"]
    result=agent.query(session,"生产1件")
    assert result["status"] == "ok" and result["structured_data"]["data"]["requested_quantity"] == 1


def test_known_shortage_calculated_despite_unknown_records(book,tmp_path):
    authorize(book,tmp_path)
    data=book[0].analyze("ENTERPRISE-A",quantity=100)["data"]
    assert data["quantity_review"] and data["inventory_sufficient_for_requested"] is False
    zero=data["materials"][1]; unknown=data["materials"][2]
    assert zero["actual_stock_qty"] == "0" and Decimal(zero["shortage_qty"]) > 0
    assert unknown["actual_stock_qty"] is unknown["shortage_qty"] is None
    assert data["book_shortages"] and not data["formal_production_approved"]


def test_no_shortage_not_equal_full_readiness(book,tmp_path):
    service,_,_,codes,path=book
    stock_file(path,[["SITE","A",codes[0],"A","L1",999999,"片"]],True)
    authorize(book,tmp_path)
    data=service.analyze("ENTERPRISE-A",quantity=1)["data"]
    assert not data["book_shortages"] and data["inventory_sufficient_for_requested"] is None


def test_full_positive_and_negative_same_service(book,tmp_path):
    service,_,_,_,path=book
    bom=service.facts.query_bom("ENTERPRISE-A","V01")["data"]["lines"]
    stock_file(path,[["SITE",str(i),r["child_item"]["material_code"],"Synthetic","L1",
        str(Decimal(r["qty_per"])*50),"片"] for i,r in enumerate(bom)],True)
    authorize(book,tmp_path)
    yes=service.analyze("ENTERPRISE-A",quantity=50)
    no=service.analyze("ENTERPRISE-A",quantity=100)
    assert yes["data"]["inventory_sufficient_for_requested"] is True
    assert no["data"]["inventory_sufficient_for_requested"] is False
    assert not yes["data"]["formal_production_approved"]
    assert yes["provenance"]["quantity_confirmation"]["confirmation_id"]


@pytest.mark.parametrize("changes", [dict(content_sha256="0"*64),dict(sheet_name="Excluded"),
    dict(product_scope=[dict(product="UNAPPROVED",revision="V01")])])
def test_scope_does_not_authorize_other_source_or_product(book,tmp_path,changes):
    authorize(book,tmp_path,**changes)
    assert not book[0].analyze("ENTERPRISE-A",quantity=1)["data"]["quantity_review"]


def test_duplicates_never_become_verified_stock(book,tmp_path):
    service,_,_,codes,path=book
    row=["SITE","A",codes[0],"A","L1",999,"片"]
    stock_file(path,[row,row],True);authorize(book,tmp_path)
    data=service.analyze("ENTERPRISE-A",quantity=1)["data"]
    assert data["materials"][0]["actual_stock_qty"] is None
    assert data["materials"][0]["shortage_qty"] is None
    assert len(data["materials"][0]["details"]) == 2


def test_missing_quantity_asks_only_quantity_then_accepts_bare_count(book,tmp_path):
    authorize(book,tmp_path)
    service,agent,session,_,_=book
    with patch.object(service.observations,"load",side_effect=AssertionError("No quantity, no stock read")):
        result=agent.query(session,"我要生产ENTERPRISE-A")
    assert result["status"] == "needs_input"
    assert result["structured_data"]["missing_parameters"] == ["quantity"]
    assert "66" in result["answer"] and "快照" not in result["answer"]
    assert agent.repository.get_session(session)["context"]["production"]["material_code"] == "ENTERPRISE-A"
    result=agent.query(session,"50片")
    assert result["status"] == "ok"
    assert result["structured_data"]["data"]["requested_quantity"] == 50


def test_shortage_followups_reuse_the_latest_quantity_evidence(book,tmp_path):
    authorize(book,tmp_path)
    service,agent,session,_,_=book
    agent.query(session,"生产100片ENTERPRISE-A")
    latest=agent.query(session,"生产50个呢")
    with patch.object(service,"analyze",side_effect=AssertionError("Reuse latest Evidence")):
        for message in ["哪些物料不足？","为什么不能生产？","哪些物料影响最大？","限制在哪里？"]:
            result=agent.query(session,message)
            assert result["structured_data"]["data"] == latest["structured_data"]["data"], message
            assert result["structured_data"]["completed_steps"] == []
            assert result["structured_data"]["reused_from_turn_id"]
