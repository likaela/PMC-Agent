"""采购在途事实合同和受控导入测试。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fact_layer.models import ImportBatchStatus, InboundSupplyInputRow
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from repositories.inbound_supply_import_repository import current_real_inbound_availability
from services.inbound_supply_import_service import InboundSupplyImportService
from tests.test_inventory_fact_import import _seed_item


class InboundSupplyFactImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.repository = FactRepository(SQLiteFactStore(self.temp_path / "facts.db"))
        self.repository.migrate()
        self.service = InboundSupplyImportService(self.repository)
        self.source = self.temp_path / "authoritative-po-source.txt"
        self.source.write_text("fixture provenance only", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_in_transit_is_calculated_only_when_received_quantity_is_known(self) -> None:
        _seed_item(self.repository, "MAT-001")
        rows = [
            InboundSupplyInputRow(
                "采购订单",
                2,
                "MAT-001",
                10,
                received_qty=3,
                supplier_code="SUP-1",
                order_no="PO-1",
            ),
            InboundSupplyInputRow(
                "采购订单",
                3,
                "MAT-001",
                5,
                received_qty=None,
                supplier_code="SUP-1",
                order_no="PO-2",
            ),
        ]

        staged = self.service.stage_rows(
            self.source,
            "fixture_purchase_orders",
            rows,
            observed_at=datetime(2026, 9, 29, tzinfo=UTC),
        )
        stored = self.service.repository.get_staged_rows(staged.import_batch_id)
        published = self.service.publish(staged.import_batch_id)

        self.assertEqual(staged.status, ImportBatchStatus.READY_TO_PUBLISH)
        self.assertEqual(stored[0].in_transit_qty, Decimal("7"))
        self.assertIsNone(stored[1].received_qty)
        self.assertIsNone(stored[1].in_transit_qty)
        self.assertEqual(published["fact_count"], 2)

    def test_invalid_and_missing_fields_are_rejected_with_reasons(self) -> None:
        rows = [
            InboundSupplyInputRow("采购订单", 2, None, 10),
            InboundSupplyInputRow("采购订单", 3, "MAT-X", -1),
            InboundSupplyInputRow("采购订单", 4, "MAT-Y", 5, received_qty=6),
        ]

        staged = self.service.stage_rows(
            self.source,
            "fixture_purchase_orders",
            rows,
        )

        self.assertEqual(staged.status, ImportBatchStatus.INVALID)
        self.assertEqual(
            {error.error_code for error in staged.errors},
            {"MATERIAL_CODE_REQUIRED", "ORDERED_QTY_INVALID", "RECEIVED_QTY_INVALID"},
        )
        with self.assertRaisesRegex(ValueError, "不能发布"):
            self.service.publish(staged.import_batch_id)
        self.assertEqual(self.service.repository.count_published_facts(), 0)

    def test_unmatched_item_is_explicitly_pending(self) -> None:
        staged = self.service.stage_rows(
            self.source,
            "fixture_purchase_orders",
            [InboundSupplyInputRow("采购订单", 2, "UNKNOWN", 10, received_qty=0)],
        )

        self.assertEqual(staged.status, ImportBatchStatus.PENDING_CONFIRMATION)
        self.assertEqual(staged.unmatched_item_count, 1)
        self.assertIn("item_mapping", staged.pending_confirmation_fields)

    def test_current_enterprise_sources_do_not_generate_fake_inbound_facts(self) -> None:
        availability = current_real_inbound_availability()

        self.assertFalse(availability["real_inbound_facts_available"])
        self.assertEqual(availability["published_fact_count"], 0)
        self.assertEqual(self.service.repository.count_published_facts(), 0)


if __name__ == "__main__":
    unittest.main()
