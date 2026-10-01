"""v1.11 synthetic published facts：批次、预警、FIFO 与开工日在途。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from repositories.fact_repository import FactRepository
from repositories.fact_store import MIGRATIONS_ROOT, SQLiteFactStore
from repositories.inventory_analysis_repository import InventoryAnalysisRepository
from services.published_inventory_analysis_service import PublishedInventoryAnalysisService
from tests.test_inventory_fact_import import _seed_item
from tools.agent_tools import ALL_AGENT_TOOLS
from tools.fact_query_tools import FACT_QUERY_TOOLS
from tools.inventory_analysis_tools import (
    INVENTORY_ANALYSIS_TOOLS, published_inventory_fifo_plan,
    published_inventory_risk_analysis, published_supply_by_start_query,
)


AT = "2026-10-01T00:00:00+00:00"


class PublishedInventoryAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "facts.db"
        self.store = SQLiteFactStore(self.database)
        self.facts = FactRepository(self.store)
        self.facts.migrate()
        self.item_id = _seed_item(self.facts, "MAT-001")
        self.repository = InventoryAnalysisRepository(self.facts)
        self.service = PublishedInventoryAnalysisService(self.repository)

    def _source(self, name: str, status: str = "published") -> tuple[str, str]:
        batch, source = str(uuid4()), str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO import_batches (id, mapping_name, status, created_at, published_at) VALUES (?, ?, ?, ?, ?)",
                (batch, "synthetic-v1.11", status, AT, AT))
            self.store.execute(connection,
                "INSERT INTO source_files (id, import_batch_id, original_filename, content_sha256, byte_size, "
                "source_kind, source_uri, immutable_copy) VALUES (?, ?, ?, ?, 1, 'local', ?, ?)",
                (source, batch, name, "b" * 64, f"test://{name}", False))
        return batch, source

    def _inventory(self, rows: list[dict], *, at: str = AT, status: str = "published") -> str:
        batch, source = self._source(f"stock-{uuid4().hex}.xlsx", status)
        snapshot = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inventory_snapshots (id, snapshot_at, observed_at, import_batch_id, source_file_id, "
                "source_content_sha256, source_sheet, published_at) VALUES (?, ?, ?, ?, ?, ?, '库存', ?)",
                (snapshot, at, at, batch, source, source, AT))
            for row_number, row in enumerate(rows, 2):
                self.store.execute(connection,
                    "INSERT INTO inventory_facts (id, inventory_snapshot_id, item_id, raw_material_code, batch_no, "
                    "warehouse, location, on_hand_qty, reserved_qty, available_qty, received_at, last_movement_at, "
                    "expiry_date, import_batch_id, source_file_id, source_sheet, source_row_number, is_duplicate) "
                    "VALUES (?, ?, ?, 'MAT-001', ?, 'W1', ?, ?, ?, ?, ?, ?, ?, ?, ?, '库存', ?, ?)",
                    (str(uuid4()), snapshot, self.item_id, row.get("batch_no", f"B{row_number}"),
                     row.get("location", f"L{row_number}"), row.get("on_hand_qty", "10"), row.get("reserved_qty"),
                     row.get("available_qty"), row.get("received_at"), row.get("last_movement_at"),
                     row.get("expiry_date"), batch, source, row_number, row.get("is_duplicate", False)))
        return batch

    def _policy(self, *, safety: str | None = "12", unit: str = "件", expiry: int | None = 7,
                stagnant: int | None = 90, status: str = "published", start: str = "2026-09-01") -> str:
        batch, source = self._source("inventory-policy.xlsx", status)
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inventory_risk_policies (id, item_id, safety_stock_qty, unit, expiry_warning_days, "
                "stagnant_days, effective_from, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '规则', 2)",
                (str(uuid4()), self.item_id, safety, unit, expiry, stagnant, start, batch, source))
        return batch

    def _inbound(self, rows: list[dict], *, at: str = AT, status: str = "published") -> str:
        batch, source = self._source(f"purchase-{uuid4().hex}.xlsx", status)
        observation = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inbound_supply_observations (id, observed_at, import_batch_id, source_file_id, "
                "source_content_sha256, source_name, published_at) VALUES (?, ?, ?, ?, ?, '标准采购事实', ?)",
                (observation, at, batch, source, source, AT))
            for row_number, row in enumerate(rows, 2):
                self.store.execute(connection,
                    "INSERT INTO inbound_supply_facts (id, inbound_observation_id, item_id, raw_material_code, "
                    "order_no, ordered_qty, received_qty, in_transit_qty, expected_arrival_date, committed_date, "
                    "supply_status, import_batch_id, source_file_id, source_sheet, source_row_number) "
                    "VALUES (?, ?, ?, 'MAT-001', ?, ?, ?, ?, ?, ?, ?, ?, ?, '采购', ?)",
                    (str(uuid4()), observation, self.item_id, row.get("order_no", f"PO-{row_number}"),
                     row.get("ordered_qty", "10"), row.get("received_qty", "0"), row.get("in_transit_qty", "10"),
                     row.get("expected_arrival_date"), row.get("committed_date"),
                     row.get("status", "confirmed"), batch, source, row_number))
        return batch

    def test_lot_rows_preserve_same_batch_different_locations_and_sources(self) -> None:
        batch = self._inventory([{"batch_no": "B1", "location": "A"}, {"batch_no": "B1", "location": "B"}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["on_hand_qty"], "20")
        lots = result["data"]["inventory_lots"]
        self.assertEqual([lot["location"] for lot in lots], ["A", "B"])
        self.assertEqual([lot["provenance"]["row_number"] for lot in lots], [2, 3])
        self.assertEqual(result["provenance"]["import_batch_id"], batch)
        self.assertEqual(lots[0]["provenance"]["content_sha256"], "b" * 64)
        self.assertEqual(lots[0]["snapshot_at"], AT)

    def test_unknown_reserved_stays_null_even_when_available_is_authoritative(self) -> None:
        self._inventory([{"available_qty": "7"}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertIsNone(result["data"]["reserved_qty"])
        self.assertEqual(result["data"]["available_qty"], "7")
        self.assertFalse(result["completeness"]["reserved_qty"])

    def test_unknown_available_not_implicitly_equal_to_on_hand(self) -> None:
        self._inventory([{"reserved_qty": "2"}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertIsNone(result["data"]["available_qty"])
        self.assertFalse(result["completeness"]["available_qty"])

    def test_explicit_calculation_requires_both_authoritative_operands(self) -> None:
        self._inventory([{"on_hand_qty": "10.25", "reserved_qty": "2.5"}])
        result = self.service.analyze("MAT-001", as_of=AT, availability_basis="on_hand_minus_reserved")
        self.assertEqual(result["data"]["available_qty"], "7.75")
        self.assertEqual(result["data"]["inventory_lots"][0]["available_basis"], "explicit_on_hand_minus_reserved")

    def test_unknown_reservation_prevents_explicit_calculation(self) -> None:
        self._inventory([{}])
        result = self.service.analyze("MAT-001", as_of=AT, availability_basis="on_hand_minus_reserved")
        self.assertIsNone(result["data"]["available_qty"])

    def test_invalid_or_conflicting_quantities_refuse_allocation(self) -> None:
        for index, row in enumerate(({"available_qty": "NaN"}, {"reserved_qty": "11", "available_qty": "1"},
                                     {"available_qty": "-1"}, {"on_hand_qty": "10", "reserved_qty": "5", "available_qty": "6"})):
            with self.subTest(row=row):
                # 每个异常场景独立快照，最新观察以不同时间隔离。
                stamp = f"2026-09-{20 + index:02}T00:00:00+00:00"
                self._inventory([row], at=stamp)
                result = self.service.fifo("MAT-001", "1", as_of=AT)
                self.assertEqual(result["status"], "data_unavailable")
                self.assertIsNone(result["data"]["allocations"])
                self.assertFalse(result["completeness"]["quantity_valid"])

    def test_fifo_decimal_allocation_and_readonly_simulation(self) -> None:
        self._inventory([
            {"batch_no": "NEW", "available_qty": "6", "received_at": "2026-09-02T00:00:00+00:00"},
            {"batch_no": "OLD", "available_qty": "4.5", "received_at": "2026-09-01T00:00:00+00:00"},
        ])
        result = self.service.fifo("MAT-001", "7.25", as_of=AT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([line["batch_no"] for line in result["data"]["allocations"]], ["OLD", "NEW"])
        self.assertEqual([line["allocated_qty"] for line in result["data"]["allocations"]], ["4.5", "2.75"])
        self.assertEqual(result["data"]["allocations"][-1]["available_after"], "3.25")
        self.assertEqual(result["data"]["shortage_qty"], "0.00")
        self.assertTrue(result["data"]["simulation_only"])
        self.assertEqual(self.service.analyze("MAT-001", as_of=AT)["data"]["available_qty"], "10.5")

    def test_fifo_ties_have_stable_order_and_partial_shortage(self) -> None:
        received = "2026-09-01T00:00:00+00:00"
        self._inventory([{"location": "Z", "available_qty": "1", "received_at": received},
                         {"location": "A", "available_qty": "2", "received_at": received}])
        first = self.service.fifo("MAT-001", "5", as_of=AT)
        second = self.service.fifo("MAT-001", "5", as_of=AT)
        self.assertEqual(first, second)
        self.assertEqual([row["location"] for row in first["data"]["allocations"]], ["A", "Z"])
        self.assertEqual(first["data"]["shortage_qty"], "2")

    def test_missing_fifo_date_refuses_and_does_not_substitute_expiry(self) -> None:
        self._inventory([{"available_qty": "5", "expiry_date": "2026-12-01"}])
        result = self.service.fifo("MAT-001", "1", as_of=AT)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"]["allocations"])

    def test_missing_batch_identifier_refuses_fifo(self) -> None:
        self._inventory([{"batch_no": None, "available_qty": "5", "received_at": AT}])
        self.assertEqual(self.service.fifo("MAT-001", "1", as_of=AT)["status"], "data_unavailable")

    def test_fifo_does_not_consume_expired_batch(self) -> None:
        self._inventory([{"available_qty": "8", "received_at": "2026-09-01T00:00:00+00:00", "expiry_date": "2026-09-30"},
                         {"available_qty": "2", "received_at": "2026-09-02T00:00:00+00:00", "expiry_date": "2026-10-01"}])
        result = self.service.fifo("MAT-001", "3", as_of=AT)
        self.assertEqual(result["data"]["allocated_qty"], "2")
        self.assertEqual(result["data"]["shortage_qty"], "1")
        self.assertEqual(len(result["data"]["excluded_expired_lots"]), 1)

    def test_duplicate_flag_prevents_totals_and_fifo(self) -> None:
        self._inventory([{"available_qty": "5", "received_at": AT, "is_duplicate": True}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertIsNone(result["data"]["on_hand_qty"])
        self.assertFalse(result["completeness"]["duplicate_free"])
        self.assertEqual(self.service.fifo("MAT-001", "1", as_of=AT)["status"], "data_unavailable")

    def test_expiry_alert_boundaries_and_missing_date(self) -> None:
        self._inventory([{"expiry_date": "2026-09-30"}, {"expiry_date": "2026-10-08"},
                         {"expiry_date": "2026-10-09"}, {}])
        result = self.service.analyze("MAT-001", as_of=AT, expiry_warning_days=7)
        rows = result["data"]["expiry_assessments"]
        self.assertEqual([row["status"] for row in rows], ["expired", "near_expiry", "normal", "data_unavailable"])
        self.assertEqual([row["days_remaining"] for row in rows], [-1, 7, 8, None])
        self.assertIsNone(rows[-1]["suggested_action"])
        self.assertFalse(result["completeness"]["expiry_analysis"])

    def test_stagnant_uses_movement_then_received_and_keeps_missing_unknown(self) -> None:
        self._inventory([
            {"received_at": "2026-01-01T00:00:00+00:00", "last_movement_at": "2026-09-30T00:00:00+00:00"},
            {"received_at": "2026-01-01T00:00:00+00:00"}, {},
        ])
        result = self.service.analyze("MAT-001", as_of=AT, stagnant_days=90)
        rows = result["data"]["stagnant_assessments"]
        self.assertEqual([row["status"] for row in rows], ["normal", "stagnant", "data_unavailable"])
        self.assertEqual([row["date_basis"] for row in rows], ["last_movement_at", "received_at", None])
        self.assertIsNone(rows[-1]["age_days"])

    def test_future_receipt_date_cannot_generate_fifo_result(self) -> None:
        self._inventory([{"received_at": "2026-10-02T00:00:00+00:00", "available_qty": "5"}])
        self.assertEqual(self.service.fifo("MAT-001", "1", as_of=AT)["status"], "data_unavailable")

    def test_invalid_movement_date_is_not_replaced_by_received_age_judgment(self) -> None:
        self._inventory([{"received_at": "2026-01-01T00:00:00+00:00", "last_movement_at": "2026-10-02T00:00:00+00:00"}])
        result = self.service.analyze("MAT-001", as_of=AT, stagnant_days=90)
        self.assertEqual(result["data"]["stagnant_assessments"][0]["status"], "data_unavailable")
        self.assertIsNone(result["data"]["stagnant_assessments"][0]["age_days"])

    def test_safety_stock_warning_uses_published_policy_and_provenance(self) -> None:
        self._inventory([{"available_qty": "8"}])
        batch = self._policy()
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["data"]["safety_stock"], {"status": "below_safety_stock", "safety_stock_qty": "12", "gap_qty": "4"})
        self.assertEqual(result["provenance"]["risk_policy"]["import_batch_id"], batch)

    def test_missing_policy_does_not_default_safety_stock_to_zero(self) -> None:
        self._inventory([{"available_qty": "10"}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertIsNone(result["data"]["safety_stock"]["safety_stock_qty"])
        self.assertFalse(result["completeness"]["safety_stock_analysis"])

    def test_zero_safety_policy_is_valid(self) -> None:
        self._inventory([{"available_qty": "0", "reserved_qty": "0"}])
        self._policy(safety="0")
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["data"]["safety_stock"]["status"], "normal")
        self.assertEqual(result["data"]["safety_stock"]["safety_stock_qty"], "0")

    def test_policy_unit_conflict_and_overlapping_versions_refuse_safety_judgment(self) -> None:
        self._inventory([{"available_qty": "1"}])
        self._policy(unit="kg")
        self.assertFalse(self.service.analyze("MAT-001", as_of=AT)["completeness"]["safety_stock_analysis"])
        self._policy()
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertIsNone(result["data"]["safety_stock"]["gap_qty"])

    def test_inbound_cutoff_and_committed_date_priority(self) -> None:
        self._inventory([{"available_qty": "5", "expiry_date": "2027-01-01"}])
        self._inbound([
            {"expected_arrival_date": "2026-10-03"},
            {"expected_arrival_date": "2026-10-04"},
            {"expected_arrival_date": "2026-10-03", "committed_date": "2026-10-05"},
        ])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["eligible_inbound_qty"], "10")
        self.assertEqual(result["data"]["planned_supply_qty"], "15")
        self.assertEqual([row["planning_status"] for row in result["data"]["lines"]], ["eligible", "excluded", "excluded"])
        self.assertEqual(result["data"]["lines"][2]["arrival_basis"], "committed_date")
        self.assertEqual(result["provenance"]["inbound"]["lines"][0]["row_number"], 2)

    def test_missing_inbound_dates_or_remaining_quantity_keep_full_plan_unknown(self) -> None:
        self._inventory([{"available_qty": "5"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"},
                       {"received_qty": None, "in_transit_qty": None, "expected_arrival_date": "2026-10-03"},
                       {}])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertEqual(result["data"]["known_eligible_inbound_qty"], "10")
        self.assertIsNone(result["data"]["eligible_inbound_qty"])
        self.assertIsNone(result["data"]["planned_supply_qty"])

    def test_unknown_or_overdue_inbound_status_does_not_count(self) -> None:
        self._inventory([{"available_qty": "5"}])
        self._inbound([{"status": None, "expected_arrival_date": "2026-10-03"},
                       {"expected_arrival_date": "2026-09-30"}])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertFalse(result["completeness"]["inbound"])
        self.assertIsNone(result["data"]["eligible_inbound_qty"])
        self.assertEqual(result["data"]["known_eligible_inbound_qty"], "0")

    def test_closed_order_excluded_and_explicit_remaining_calculated(self) -> None:
        self._inventory([{"available_qty": "5", "expiry_date": "2027-01-01"}])
        self._inbound([{"status": "cancelled"}, {"received_qty": "3", "in_transit_qty": None, "expected_arrival_date": "2026-10-03"}])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["data"]["eligible_inbound_qty"], "7")
        self.assertEqual(result["data"]["planned_supply_qty"], "12")

    def test_no_published_inbound_does_not_return_zero(self) -> None:
        self._inventory([{"available_qty": "5"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"}], status="staging")
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"]["eligible_inbound_qty"])

    def test_planned_supply_excludes_stock_expired_before_start(self) -> None:
        self._inventory([{"available_qty": "5", "expiry_date": "2026-10-02"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"}])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["current_available_qty"], "5")
        self.assertEqual(result["data"]["inventory_usable_at_start_qty"], "0")
        self.assertEqual(result["data"]["planned_supply_qty"], "10")

    def test_unknown_stock_expiry_does_not_prove_future_availability(self) -> None:
        self._inventory([{"available_qty": "5"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"}])
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["data"]["eligible_inbound_qty"], "10")
        self.assertIsNone(result["data"]["inventory_usable_at_start_qty"])
        self.assertIsNone(result["data"]["planned_supply_qty"])

    def test_observation_mismatch_prevents_double_counting_received_stock(self) -> None:
        self._inventory([{"available_qty": "5"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"}], at="2026-09-30T00:00:00+00:00")
        result = self.service.planned_supply("MAT-001", "2026-10-04", as_of=AT)
        self.assertEqual(result["data"]["eligible_inbound_qty"], "10")
        self.assertIsNone(result["data"]["planned_supply_qty"])
        self.assertFalse(result["completeness"]["observation_coherent"])

    def test_future_and_unpublished_inventory_are_not_used(self) -> None:
        self._inventory([{"on_hand_qty": "6"}], at="2026-09-30T00:00:00+00:00")
        self._inventory([{"on_hand_qty": "9"}], at=AT, status="staging")
        self._inventory([{"on_hand_qty": "99"}], at="2026-10-02T00:00:00+00:00")
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["data"]["on_hand_qty"], "6")

    def test_same_time_snapshot_conflict_is_not_arbitrarily_selected(self) -> None:
        self._inventory([{"on_hand_qty": "6"}])
        self._inventory([{"on_hand_qty": "9"}])
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"])

    def test_sqlite_as_of_respects_timezone_instead_of_string_order(self) -> None:
        self._inventory([{"on_hand_qty": "6"}], at="2026-10-01T07:00:00+08:00")
        self._inventory([{"on_hand_qty": "99"}], at="2026-09-30T23:30:00-01:00")
        result = self.service.analyze("MAT-001", as_of=AT)
        self.assertEqual(result["data"]["on_hand_qty"], "6")
        self.assertEqual(result["data"]["snapshot_at"], "2026-09-30T23:00:00+00:00")

    def test_new_tools_are_independent_and_delegate_to_services(self) -> None:
        self._inventory([{"available_qty": "5", "received_at": AT, "expiry_date": "2027-01-01"}])
        self._inbound([{"expected_arrival_date": "2026-10-03"}])
        names = {tool.name for tool in INVENTORY_ANALYSIS_TOOLS}
        self.assertTrue(names.isdisjoint({tool.name for tool in FACT_QUERY_TOOLS + ALL_AGENT_TOOLS}))
        with patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{self.database.as_posix()}"}):
            result = published_inventory_risk_analysis.invoke({"material_code": "MAT-001", "as_of": AT})
            fifo = published_inventory_fifo_plan.invoke({"material_code": "MAT-001", "required_qty": "2", "as_of": AT})
            supply = published_supply_by_start_query.invoke({"material_code": "MAT-001", "start_date": "2026-10-04", "as_of": AT})
        self.assertEqual(result, self.service.analyze("MAT-001", as_of=AT))
        self.assertEqual(fifo["data"]["allocated_qty"], "2")
        self.assertEqual(supply["data"]["planned_supply_qty"], "15")

    def test_invalid_queries_and_unknown_item_do_not_create_numbers(self) -> None:
        self.assertEqual(self.service.analyze("MISSING", as_of=AT)["status"], "item_not_found")
        self.assertEqual(self.service.analyze("MAT-001", as_of="2026-10-01")["status"], "invalid_query")
        self.assertEqual(self.service.analyze("MAT-001", as_of=AT, stagnant_days=0)["status"], "invalid_query")
        self.assertEqual(self.service.fifo("MAT-001", "NaN", as_of=AT)["status"], "invalid_query")

    def test_migration_from_v110_preserves_existing_item_and_adds_nullable_event(self) -> None:
        migration_fixture = self.root / "prior-migrations" / "sqlite"
        migration_fixture.mkdir(parents=True)
        for source in (MIGRATIONS_ROOT / "sqlite").glob("*.sql"):
            if source.name < "005":
                shutil.copyfile(source, migration_fixture / source.name)
        store = SQLiteFactStore(self.root / "prior-facts.db")
        facts = FactRepository(store)
        with patch("repositories.fact_store.MIGRATIONS_ROOT", migration_fixture.parent):
            facts.migrate()
        item_id = _seed_item(facts, "PRIOR-ITEM")
        with store.transaction() as connection:
            batch, source = store.execute(connection, "SELECT import_batch_id, source_file_id FROM items WHERE id = ?", (item_id,)).fetchone()
            store.execute(connection,
                "INSERT INTO inventory_snapshots (id, snapshot_at, observed_at, import_batch_id, source_file_id, source_content_sha256, source_sheet, published_at) "
                "VALUES ('old-snapshot', ?, ?, ?, ?, ?, '旧库存', ?)", (AT, AT, batch, source, "a" * 64, AT))
            store.execute(connection,
                "INSERT INTO inventory_facts (id, inventory_snapshot_id, item_id, raw_material_code, on_hand_qty, available_qty, reserved_qty, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "VALUES ('old-lot', 'old-snapshot', ?, 'PRIOR-ITEM', '8', '7', '1', ?, ?, '旧库存', 2)", (item_id, batch, source))
        self.assertEqual(facts.migrate(), ["005_inventory_analysis"])
        self.assertEqual(facts.migrate(), [])
        with store.transaction() as connection:
            self.assertEqual(store.execute(connection, "SELECT material_code FROM items").fetchone()[0], "PRIOR-ITEM")
            old_lot = store.execute(connection, "SELECT on_hand_qty, available_qty, reserved_qty, last_movement_at FROM inventory_facts").fetchone()
            self.assertEqual(old_lot, ("8", "7", "1", None))
            fields = store.execute(connection, "PRAGMA table_info(inventory_facts)").fetchall()
        self.assertIn("last_movement_at", [row[1] for row in fields])


if __name__ == "__main__":
    unittest.main()
