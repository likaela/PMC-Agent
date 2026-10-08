"""Prepublication checks use normalized rows, not an LLM or published writes."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from io import BytesIO, TextIOWrapper
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import check_enterprise_data_readiness as checker
from services.enterprise_data_readiness_service import (
    build_enterprise_readiness_report, render_enterprise_readiness_report,
)


@pytest.fixture
def complete_data():
    return {
        "product": "TEST-PRODUCT", "revision": "V01", "parent_unit": "台",
        "bom_lines": [{"material_code": "MAT-A", "quantity": "2", "unit": "件",
            "validation_status": "valid", "unit_price": "10.50", "currency": "CNY",
            "effective_from": "2025-03-18"},
            {"material_code": "MAT-B", "quantity": "3", "unit": "件",
            "validation_status": "valid", "unit_price": "0", "currency": "CNY",
            "effective_from": "2025-03-18"}],
        "inventory_rows": [{"material_code": "MAT-A", "on_hand_qty": "10", "available_qty": "8"},
            {"material_code": "MAT-B", "on_hand_qty": "0", "available_qty": "0"}],
        "snapshot_at": "2026-09-01T09:00:00+08:00", "effective_date_source": "business_confirmation",
        "available_field_present": True,
        "provenance": {"bom": {"filename": "test-bom.xls", "sha256": "a" * 64},
                       "inventory": {"filename": "test-inventory.xlsx", "sha256": "b" * 64}},
    }


def test_complete_prerequisites_never_claim_ready_for_production(complete_data):
    report = build_enterprise_readiness_report(**complete_data)
    assert report["production_analysis"]["data_ready"]
    assert report["production_analysis"]["can_produce"] is None
    assert not report["publication_executed"]
    assert report["price"]["can_calculate_cost"]
    assert "不等于库存齐套" in " ".join(report["limitations"])


def test_zero_is_covered_null_is_not(complete_data):
    zero = build_enterprise_readiness_report(**complete_data)
    assert zero["inventory"]["available_coverage"]["known_material_count"] == 2
    complete_data["inventory_rows"][1]["available_qty"] = None
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["available_coverage"]["known_material_count"] == 1
    assert report["inventory"]["available_coverage"]["unknown_material_codes"] == ["MAT-B"]
    assert not report["production_analysis"]["data_ready"]


def test_on_hand_is_never_substituted_for_available(complete_data):
    complete_data["available_field_present"] = False
    for row in complete_data["inventory_rows"]:
        row["available_qty"] = None
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["on_hand_coverage"]["known_material_count"] == 2
    assert report["inventory"]["available_coverage"]["known_material_count"] == 0
    assert report["inventory"]["available_coverage"]["field_status"] == "not_provided"
    assert any("可用性确认" in reason for reason in report["production_analysis"]["reasons"])


def test_coverage_is_material_count_not_lot_count(complete_data):
    complete_data["inventory_rows"].append({"material_code": "MAT-A", "on_hand_qty": "5", "available_qty": "5"})
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["on_hand_coverage"]["known_material_count"] == 2
    assert report["inventory"]["on_hand_coverage"]["ratio"] == "1"
    complete_data["inventory_rows"][-1]["available_qty"] = None
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["available_coverage"]["known_material_count"] == 1
    assert report["inventory"]["available_coverage"]["unknown_material_codes"] == ["MAT-A"]


def test_missing_inventory_remains_unknown(complete_data):
    complete_data["inventory_rows"] = complete_data["inventory_rows"][:1]
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["on_hand_coverage"]["unknown_material_count"] == 1
    assert "缺口" not in report["inventory"]
    assert report["production_analysis"]["can_produce"] is None


def test_confirmed_date_preserved_without_guessing_units_or_snapshot(complete_data):
    complete_data["parent_unit"] = None
    complete_data["snapshot_at"] = None
    for row in complete_data["bom_lines"]:
        row["unit"] = None
    report = build_enterprise_readiness_report(**complete_data)
    assert report["bom"]["effective_date"]["value"] == "2025-03-18"
    assert report["bom"]["effective_date"]["status"] == "confirmed"
    assert not report["bom"]["unit_completeness"]["complete"]
    assert report["inventory"]["snapshot_at"]["status"] == "pending_confirmation"
    text = render_enterprise_readiness_report(report)
    assert "生效日期：2025-03-18（业务确认）" in text
    assert "成品单位：待确认" in text


@pytest.mark.parametrize("dates,expected", [
    ([None, None], "pending_confirmation"), (["2025-03-18", None], "pending_confirmation"),
    (["2025-03-18", "2025-04-18"], "conflicting"), (["not-a-date", "not-a-date"], "invalid"),
])
def test_missing_conflicting_invalid_dates_block_analysis(complete_data, dates, expected):
    for row, value in zip(complete_data["bom_lines"], dates):
        row["effective_from"] = value
    report = build_enterprise_readiness_report(**complete_data)
    assert report["bom"]["effective_date"]["status"] == expected
    assert not report["production_analysis"]["data_ready"]


def test_naive_snapshot_not_treated_as_confirmed(complete_data):
    complete_data["snapshot_at"] = "2026-09-01T09:00:00"
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["snapshot_at"]["status"] == "invalid"
    assert not report["production_analysis"]["data_ready"]


def test_price_absence_blocks_cost_but_not_inventory_analysis(complete_data):
    for row in complete_data["bom_lines"]:
        row["unit_price"] = None
        row["currency"] = None
    report = build_enterprise_readiness_report(**complete_data)
    assert not report["price"]["can_calculate_cost"]
    assert report["price"]["priced_line_count"] == 0
    assert report["production_analysis"]["data_ready"]


def test_multiple_currencies_not_implicitly_converted(complete_data):
    complete_data["bom_lines"][1]["currency"] = "USD"
    report = build_enterprise_readiness_report(**complete_data)
    assert not report["price"]["can_calculate_cost"]
    assert any("多个币种" in reason for reason in report["price"]["reasons"])


@pytest.mark.parametrize("value", ["-1", "not-a-number", "NaN", "Infinity", True])
def test_invalid_stock_is_not_counted_as_known(complete_data, value):
    complete_data["inventory_rows"][0]["on_hand_qty"] = value
    report = build_enterprise_readiness_report(**complete_data)
    assert report["inventory"]["on_hand_coverage"]["known_material_count"] == 1
    assert not report["production_analysis"]["data_ready"]


def test_validation_errors_block_otherwise_complete_data(complete_data):
    complete_data["validation_errors"] = [{"code": "DUPLICATE_BOM_LINE", "row": 4}]
    report = build_enterprise_readiness_report(**complete_data)
    assert not report["production_analysis"]["data_ready"]
    assert not report["price"]["can_calculate_cost"]


def test_empty_input_does_not_become_100_percent_ready():
    report = build_enterprise_readiness_report(product="", revision="", bom_lines=[],
        parent_unit=None, inventory_rows=[], snapshot_at=None)
    assert report["inventory"]["available_coverage"]["ratio"] is None
    assert not report["price"]["can_calculate_cost"]
    assert not report["production_analysis"]["data_ready"]


def test_report_preserves_provenance_and_does_not_mutate_inputs(complete_data):
    before = deepcopy(complete_data)
    report = build_enterprise_readiness_report(**complete_data)
    assert complete_data == before
    assert report["provenance"] == before["provenance"]
    assert "test-bom.xls" in render_enterprise_readiness_report(report)


def test_checker_writes_both_reports_without_import_or_publish(tmp_path, complete_data, monkeypatch):
    confirmations_path = tmp_path / "confirmation.json"
    confirmations_path.write_text(json.dumps({"effective_from": "2025-03-18"}), encoding="utf-8")
    outputs = [tmp_path / "readiness.json", tmp_path / "readiness.md"]
    monkeypatch.setattr(sys, "argv", ["check", "--confirmations", str(confirmations_path),
        "--json-report", str(outputs[0]), "--markdown-report", str(outputs[1])])
    report = build_enterprise_readiness_report(**complete_data)
    with patch.object(checker, "precheck", return_value={"readiness_report": report,
            "status": "pending_confirmation", "pending_confirmation_fields": ["confirmed_by"]}) as precheck_call, \
        patch("scripts.import_kq_z112_enterprise_facts.create_fact_store", side_effect=AssertionError("no database")), \
        patch("scripts.import_kq_z112_enterprise_facts.import_enterprise", side_effect=AssertionError("no import")):
        assert checker.main() == 0
    assert precheck_call.call_args.args[2] == {"effective_from": "2025-03-18"}
    saved = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert saved["bom"]["effective_date"]["value"] == "2025-03-18"
    assert saved["publication_precheck"]["pending_confirmation_fields"] == ["confirmed_by"]
    assert not saved["publication_executed"]
    assert "数据来源" in outputs[1].read_text(encoding="utf-8")


def test_checker_rejects_publish_option(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check", "--publish"])
    with pytest.raises(SystemExit) as caught:
        checker.main()
    assert caught.value.code == 2


def test_checker_does_not_overwrite_confirmation_file(tmp_path, monkeypatch):
    confirmation = tmp_path / "confirmation.json"
    confirmation.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check", "--confirmations", str(confirmation),
        "--json-report", str(confirmation)])
    with pytest.raises(SystemExit):
        checker.main()
    assert confirmation.read_text(encoding="utf-8") == "{}"


def test_windows_gbk_output_can_display_check_marks():
    buffer = BytesIO()
    output = TextIOWrapper(buffer, encoding="gbk")
    with redirect_stdout(output):
        checker._print_report("✓ 生效日期已确认；⚠ 库存未知")
    output.flush()
    assert buffer.getvalue().decode("utf-8").strip() == "✓ 生效日期已确认；⚠ 库存未知"
