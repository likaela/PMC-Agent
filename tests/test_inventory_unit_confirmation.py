"""Explicit synthetic human confirmation, source scope and review contract."""
import hashlib
import json

import pytest

from repositories.book_inventory_repository import BookInventoryRepository
from repositories.inventory_unit_confirmation_repository import InventoryUnitConfirmationRepository
from tests.test_enterprise_book_analysis import book, stock_file
from tests.test_published_bom_business_confirmation import fixture


def attach_confirmation(book, tmp_path, **changes):
    service, _, _, _, source = book
    event = dict(source_uri=str(source), source_file=source.name,
        content_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), sheet_name="库存表",
        quantity_field="库存", unit="片", confirmed_by="Synthetic reviewer",
        reason="Explicit source unit confirmation, not availability", recorded_at="2026-10-10T00:00:00+08:00",
        user_statement="Synthetic source inventory quantities use 片", applies_to_existing_source_only=True)
    event.update(changes)
    target = tmp_path / "unit-confirmations.json"
    target.write_text(json.dumps(dict(confirmations=[event]), ensure_ascii=False), encoding="utf-8")
    service.observations = BookInventoryRepository(source, unit_confirmations=InventoryUnitConfirmationRepository(target))
    return target, event


def test_confirmed_unit_keeps_raw_quantities_and_complete_audit(book, tmp_path):
    service, _, _, codes, source = book
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    attach_confirmation(book, tmp_path)
    result = service.inventory(codes[0]); row = result["data"]["materials"][0]
    assert row["recorded_stock_qty"] == "12" and row["inventory_unit"] == "片"
    assert row["available_qty"] is row["reserved_qty"] is None
    for detail in row["details"]:
        audit = detail["provenance"]["unit_confirmation"]
        assert len(audit["confirmation_id"]) == 64
        assert audit["source_kind"] == "human_business_confirmation"
        assert audit["confirmed_by"] == "Synthetic reviewer" and audit["user_statement"]
        assert audit["content_sha256"] == before and audit["sheet_name"] == "库存表"
        assert detail["raw_inventory_unit"] is None and detail["inventory_unit"] == "片"
        assert detail["provenance"]["snapshot_at"] is None
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    assert not any("单位尚未确认" in w for w in result["warnings"])


@pytest.mark.parametrize("changes", [dict(content_sha256="0"*64), dict(source_file="another.xlsx"),
    dict(source_uri="data/raw/unapproved.xlsx"), dict(sheet_name="电阻电容现库位")])
def test_confirmation_never_applies_to_other_source(book, tmp_path, changes):
    attach_confirmation(book, tmp_path, **changes)
    result = book[0].inventory(book[3][0])
    assert result["data"]["materials"][0]["inventory_unit"] is None
    assert result["data"]["source_summary"]["unit_confirmation"] is None


def test_cached_source_reads_new_confirmation_without_changing_excel(book, tmp_path):
    service, _, _, codes, _ = book
    assert service.inventory(codes[0])["data"]["materials"][0]["inventory_unit"] is None
    attach_confirmation(book, tmp_path)
    assert service.inventory(codes[0])["data"]["materials"][0]["inventory_unit"] == "片"
    # The raw workbook cache never embeds or leaks this source-specific unit.
    unconfirmed = BookInventoryRepository(book[4], unit_confirmations=InventoryUnitConfirmationRepository(tmp_path / "absent.json"))
    assert unconfirmed.load()["records"][codes[0]][0]["inventory_unit"] is None


def test_changed_file_requires_new_confirmation(book, tmp_path):
    service, _, _, codes, path = book
    attach_confirmation(book, tmp_path)
    stock_file(path, [["SITE", "A", codes[0], "A", "LOT1", 25]])
    row = service.inventory(codes[0])["data"]["materials"][0]
    assert row["recorded_stock_qty"] == "25" and row["inventory_unit"] is None


def test_confirmation_does_not_zero_fill_or_publish_inventory(book, tmp_path):
    service = book[0]; attach_confirmation(book, tmp_path)
    result = service.analyze("ENTERPRISE-A", quantity=100, requested_unit="片")
    assert result["status"] == "ok" and result["completeness"]["demand"]
    assert len(result["data"]["materials"]) == 66
    zero = next(r for r in result["data"]["materials"] if r["material_code"] == book[3][1])
    unknown = next(r for r in result["data"]["materials"] if r["material_code"] == book[3][2])
    assert zero["recorded_stock_qty"] == "0" and zero["inventory_unit"] == "片"
    assert unknown["recorded_stock_qty"] is None and unknown["inventory_unit"] is None
    assert all(r["available_qty"] is None for r in result["data"]["materials"])
    assert result["data"]["can_start_production"] is None
    from services.production_feasibility_query_service import ProductionFeasibilityQueryService
    assert ProductionFeasibilityQueryService(service.facts).query("ENTERPRISE-A", "V01",
        requested_quantity=100, effective_date="2026-09-16")["status"] == "data_unavailable"


def test_confirmation_keeps_excluded_sheets_and_missing_unknown(book, tmp_path):
    attach_confirmation(book, tmp_path)
    data = book[0].observations.load()
    assert "UNMATCHED" not in data["records"]
    assert data["excluded_sheets"] == ["电阻电容现库位"]


def test_duplicate_records_not_a_verified_inventory_total(book, tmp_path):
    service, _, _, codes, path = book
    row = ["SITE", "A", codes[0], "A", "LOT1", 6]
    stock_file(path, [row, row]); attach_confirmation(book, tmp_path)
    result = service.inventory(codes[0]); row = result["data"]["materials"][0]
    assert row["inventory_unit"] == "片" and row["record_count"] == 2
    assert row["recorded_stock_qty"] is None and not result["completeness"]["recorded_stock_qty"]
    assert [d["recorded_stock_qty"] for d in row["details"]] == ["6", "6"]
    analysis = service.analyze("ENTERPRISE-A", quantity=100)
    assert analysis["data"]["materials"][0]["comparison_status"] == "pending_record_verification"


def test_conflicting_explicit_source_unit_fails_closed(book, tmp_path):
    service, _, _, codes, path = book
    stock_file(path, [["SITE", "A", codes[0], "A", "LOT1", 6, "kg"]], True)
    attach_confirmation(book, tmp_path)
    result = service.inventory(codes[0])
    assert result["data"]["materials"][0]["inventory_unit"] is None
    assert result["data"]["materials"][0]["details"][0]["raw_inventory_unit"] == "kg"
    assert result["data"]["source_summary"]["row_errors"][0]["reason"] == "inventory_unit_conflict"


def test_duplicate_or_invalid_confirmation_not_silently_used(book, tmp_path):
    target, event = attach_confirmation(book, tmp_path)
    target.write_text(json.dumps(dict(confirmations=[event,event])), encoding="utf-8")
    with pytest.raises(ValueError, match="Ambiguous"):
        book[0].observations.load()
    event["recorded_at"] = "2026-10-10"
    target.write_text(json.dumps(dict(confirmations=[event])), encoding="utf-8")
    with pytest.raises(ValueError):
        book[0].observations.load()


def test_trial_still_blocks_confirmed_source_before_cache(book, tmp_path, monkeypatch):
    attach_confirmation(book, tmp_path); book[0].observations.load()
    monkeypatch.setenv("PMC_TRIAL_MODE", "1")
    with pytest.raises(PermissionError):
        book[0].observations.load()


def test_agent_stock_and_demand_show_confirmed_unit_no_false_warning(book, tmp_path):
    attach_confirmation(book, tmp_path)
    _, agent, session, _, _ = book
    result = agent.query(session, "查询ENTERPRISE-A的库存")
    assert result["status"] == "ok" and "按片展示" in result["answer"]
    assert "库存单位待核实" not in result["answer"]
    result = agent.query(session, "生产100片ENTERPRISE-A需要哪些物料")
    assert result["structured_data"]["completeness"]["demand"]
    assert all(r["required_qty"] is not None for r in result["structured_data"]["data"]["materials"])
    assert "账面数量不足" not in result["answer"] and "初步补货" not in result["answer"]
