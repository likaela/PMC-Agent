"""v1.10 published facts 多层 BOM、有效期、单位与齐套回归。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from repositories.fact_query_repository import FactQueryRepository
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.fact_query_service import FactQueryService
from services.production_feasibility_query_service import ProductionFeasibilityQueryService
from services.published_planning_service import PublishedPlanningService
from tools.production_feasibility_query_tool import published_production_capacity_query


DATE = "2026-09-20"
STOCK_AT = "2026-09-20T00:00:00+00:00"


class PublishedPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "facts.db"
        self.store = SQLiteFactStore(self.database)
        self.repository = FactRepository(self.store)
        self.repository.migrate()
        self.facts = FactQueryService(FactQueryRepository(self.repository))
        self.master_batch, self.master_source = self._source("item-master.xlsx")
        self.items: dict[str, str] = {}

    def _source(self, name: str) -> tuple[str, str]:
        batch_id, source_id = str(uuid4()), str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO import_batches (id, mapping_name, status, created_at, published_at) "
                "VALUES (?, ?, 'published', ?, ?)",
                (batch_id, "synthetic-published-facts", STOCK_AT, STOCK_AT))
            self.store.execute(connection,
                "INSERT INTO source_files (id, import_batch_id, original_filename, content_sha256, "
                "byte_size, source_kind, source_uri, immutable_copy) VALUES (?, ?, ?, ?, 1, 'local', ?, 0)",
                (source_id, batch_id, name, "a" * 64, f"test://{name}"))
        return batch_id, source_id

    def _item(self, code: str, unit: str = "件") -> None:
        item_id = str(uuid4())
        self.items[code] = item_id
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO items (id, material_code, name, unit, import_batch_id, source_file_id, "
                "source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, '主数据', ?)",
                (item_id, code, code, unit, self.master_batch, self.master_source, len(self.items) + 1))

    def _bom(self, parent: str, revision: str, lines: list[tuple[str, str, str]],
             *, start: str = "2026-09-01", end: str | None = None) -> None:
        batch, source = self._source(f"{parent}-{revision}.xlsx")
        header = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO bom_headers (id, parent_material_code, version, effective_from, effective_to, "
                "import_batch_id, source_file_id, source_sheet) VALUES (?, ?, ?, ?, ?, ?, ?, 'BOM')",
                (header, parent, revision, start, end, batch, source))
            for row_number, (child, qty, unit) in enumerate(lines, 5):
                self.store.execute(connection,
                    "INSERT INTO bom_lines (id, bom_header_id, item_id, quantity, unit, import_batch_id, "
                    "source_file_id, source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, 'BOM', ?)",
                    (str(uuid4()), header, self.items[child], qty, unit, batch, source, row_number))

    def _conversion(self, code: str, from_unit: str, to_unit: str, factor: str,
                    *, start: str = "2026-09-01", end: str | None = None) -> None:
        batch, source = self._source(f"{code}-units.xlsx")
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO unit_conversions (id, item_id, from_unit, to_unit, factor, effective_from, "
                "effective_to, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '换算', 2)",
                (str(uuid4()), self.items[code], from_unit, to_unit, factor, start, end, batch, source))

    def _stock(self, quantities: dict[str, str | None]) -> None:
        batch, source = self._source("inventory-snapshot.xlsx")
        snapshot = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inventory_snapshots (id, snapshot_at, observed_at, import_batch_id, "
                "source_file_id, source_content_sha256, source_sheet, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '库存表', ?)",
                (snapshot, STOCK_AT, STOCK_AT, batch, source, "a" * 64, STOCK_AT))
            for row_number, (code, available) in enumerate(quantities.items(), 2):
                self.store.execute(connection,
                    "INSERT INTO inventory_facts (id, inventory_snapshot_id, item_id, raw_material_code, "
                    "on_hand_qty, available_qty, import_batch_id, source_file_id, source_sheet, source_row_number) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '库存表', ?)",
                    (str(uuid4()), snapshot, self.items[code], code,
                     available if available is not None else "100", available, batch, source, row_number))

    def _query(self, quantity: int | None = 1, *, date: str = DATE, revision: str = "V1",
               depth: int = 16) -> dict:
        return PublishedPlanningService(self.facts, max_depth=depth).query(
            "A", revision, date, requested_quantity=quantity, as_of=STOCK_AT,
        )

    def test_two_levels_and_maximum_with_shortages(self) -> None:
        for code in ("A", "B", "C", "D"):
            self._item(code)
        self._bom("A", "V1", [("B", "2", "件"), ("D", "1", "件")])
        self._bom("B", "V1", [("C", "3", "件")])
        self._stock({"C": "30", "D": "5"})
        result = self._query(6)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["theoretical_max_quantity"], 5)
        self.assertEqual({m["material_code"]: m["required_qty"] for m in result["data"]["materials"]}, {"C": "36", "D": "6"})
        self.assertEqual({m["material_code"]: m["shortage_qty"] for m in result["data"]["materials"]}, {"C": "6", "D": "1"})
        self.assertEqual({m["material_code"] for m in result["data"]["limiting_materials"]}, {"C", "D"})
        path = next(m for m in result["data"]["materials"] if m["material_code"] == "C")["bom_paths"][0]
        self.assertEqual([(edge["parent_material_code"], edge["child_material_code"]) for edge in path], [("A", "B"), ("B", "C")])
        self.assertEqual([edge["provenance"]["row_number"] for edge in path], [5, 5])
        self.assertEqual(path[0]["provenance"]["content_sha256"], "a" * 64)
        self.assertEqual(len(result["provenance"]["bom"]), 2)

    def test_three_levels_and_shared_leaf_aggregate_all_paths(self) -> None:
        for code in ("A", "B", "C", "D", "L"):
            self._item(code)
        self._bom("A", "V1", [("B", "2", "件"), ("D", "1", "件")])
        self._bom("B", "V1", [("C", "3", "件")])
        self._bom("C", "V1", [("L", "2", "件")])
        self._bom("D", "V1", [("L", "1", "件")])
        self._stock({"L": "65"})
        result = self._query(6)
        self.assertEqual(result["status"], "ok")
        leaf = result["data"]["materials"][0]
        self.assertEqual(leaf["required_per_product"], "13")
        self.assertEqual(leaf["required_qty"], "78")
        self.assertEqual(leaf["shortage_qty"], "13")
        self.assertEqual(len(leaf["bom_paths"]), 2)
        self.assertEqual(result["data"]["theoretical_max_quantity"], 5)

    def test_cycle_and_depth_limit_refuse_without_number(self) -> None:
        for code in ("A", "B", "C", "D"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")])
        self._bom("B", "V1", [("A", "1", "件")])
        cycle = self._query()
        self.assertEqual(cycle["status"], "data_unavailable")
        self.assertEqual(cycle["data"]["issue_code"], "bom_cycle")
        self.assertNotIn("theoretical_max_quantity", cycle["data"])

    def test_depth_limit_on_valid_chain(self) -> None:
        for code in ("A", "B", "C", "D"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")])
        self._bom("B", "V1", [("C", "1", "件")])
        self._bom("C", "V1", [("D", "1", "件")])
        result = self._query(depth=2)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertEqual(result["data"]["issue_code"], "bom_depth_exceeded")

    def test_explicit_root_revision_and_effective_interval(self) -> None:
        for code in ("A", "B", "C"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")], end="2026-09-30")
        self._bom("A", "V2", [("C", "1", "件")], start="2026-10-01")
        self._stock({"B": "5", "C": "8"})
        first = self._query(2)
        expired = self._query(2, date="2026-10-02")
        second = self._query(2, date="2026-10-02", revision="V2")
        self.assertEqual(first["data"]["materials"][0]["material_code"], "B")
        self.assertEqual(expired["status"], "data_unavailable")
        self.assertEqual(expired["data"]["issue_code"], "bom_version_unavailable")
        self.assertEqual(second["data"]["materials"][0]["material_code"], "C")

    def test_overlapping_child_versions_are_not_auto_selected(self) -> None:
        for code in ("A", "B", "C", "D"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")])
        self._bom("B", "V1", [("C", "1", "件")])
        self._bom("B", "V2", [("D", "1", "件")])
        result = self._query()
        self.assertEqual(result["status"], "data_unavailable")
        self.assertEqual(result["data"]["issue_code"], "bom_version_conflict")
        self.assertIn("多个有效 BOM 版本", result["warnings"][0])

    def test_explicit_unit_conversion_and_reverse(self) -> None:
        self._item("A")
        self._item("POWDER", "kg")
        self._bom("A", "V1", [("POWDER", "500", "g")])
        self._conversion("POWDER", "g", "kg", "0.001")
        self._stock({"POWDER": "1"})
        result = self._query(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["materials"][0]["required_qty"], "1.500")
        self.assertEqual(result["data"]["materials"][0]["shortage_qty"], "0.500")
        self.assertEqual(result["data"]["theoretical_max_quantity"], 2)
        self.assertEqual(result["provenance"]["unit_conversions"][0]["factor"], "0.001")
        self.assertEqual(result["provenance"]["unit_conversions"][0]["source_file"], "POWDER-units.xlsx")
        self.assertEqual(PublishedPlanningService(self.facts).query(
            "A", "V1", DATE, requested_quantity=1, as_of=STOCK_AT,
        )["status"], "ok")

    def test_missing_conversion_refuses_even_with_stock(self) -> None:
        self._item("A")
        self._item("POWDER", "kg")
        self._bom("A", "V1", [("POWDER", "500", "g")])
        self._stock({"POWDER": "100"})
        result = self._query(3)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertEqual(result["data"]["issue_code"], "unit_conversion_unavailable")

    def test_explicit_set_to_pieces_conversion_across_component(self) -> None:
        self._item("A")
        self._item("B", "pcs")
        self._item("C", "pcs")
        self._bom("A", "V1", [("B", "1", "set")])
        self._bom("B", "V1", [("C", "3", "pcs")])
        self._conversion("B", "set", "pcs", "4")
        self._stock({"C": "25"})
        result = self._query(2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["materials"][0]["required_per_product"], "12")
        self.assertEqual(result["data"]["materials"][0]["required_qty"], "24")
        self.assertEqual(result["data"]["theoretical_max_quantity"], 2)
        self.assertEqual(result["provenance"]["unit_conversions"][0]["content_sha256"], "a" * 64)

    def test_kit_rates_and_shortage_use_decimal(self) -> None:
        for code in ("A", "B", "C"):
            self._item(code)
        self._bom("A", "V1", [("B", "2", "件"), ("C", "2", "件")])
        self._stock({"B": "2", "C": "1"})
        result = self._query(1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["material_type_ready_rate"], "0.5")
        self.assertEqual(result["data"]["quantity_fulfillment_rate"], "0.75")
        self.assertEqual(result["data"]["theoretical_max_quantity"], 0)
        self.assertEqual(result["data"]["limiting_materials"][0]["material_code"], "C")

    def test_unknown_available_never_becomes_zero(self) -> None:
        for code in ("A", "B"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")])
        self._stock({"B": None})
        result = self._query(2)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"]["theoretical_max_quantity"])
        self.assertIsNone(result["data"]["materials"][0]["available_qty"])
        self.assertIsNone(result["data"]["materials"][0]["shortage_qty"])

    def test_mixed_units_do_not_get_invalid_quantity_rate(self) -> None:
        self._item("A")
        self._item("B", "件")
        self._item("C", "kg")
        self._bom("A", "V1", [("B", "1", "件"), ("C", "1", "kg")])
        self._stock({"B": "1", "C": "1"})
        result = self._query(1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["material_type_ready_rate"], "1")
        self.assertIsNone(result["data"]["quantity_fulfillment_rate"])

    def test_tool_explicit_date_uses_multilevel_but_legacy_entry_still_works(self) -> None:
        for code in ("A", "B", "C"):
            self._item(code)
        self._bom("A", "V1", [("B", "1", "件")])
        self._bom("B", "V1", [("C", "2", "件")])
        self._stock({"C": "10"})
        with patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{self.database.as_posix()}"}):
            new = published_production_capacity_query.invoke({
                "product": "A", "bom_version": "V1", "requested_quantity": 6,
                "effective_date": DATE, "as_of": STOCK_AT,
            })
        self.assertEqual(new["status"], "ok")
        self.assertEqual(new["data"]["theoretical_max_quantity"], 5)
        legacy = ProductionFeasibilityQueryService(self.facts).query("A", "V1", requested_quantity=6, as_of=STOCK_AT)
        self.assertEqual(legacy["data"]["calculation_scope"], "published_first_level_bom_current_available_inventory")


if __name__ == "__main__":
    unittest.main()
