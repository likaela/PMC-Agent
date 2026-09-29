"""库存时点事实 staging / validation / publish 测试。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook

from fact_layer.models import ImportBatchStatus
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.inventory_import_service import InventoryImportService
from scripts.validate_real_inventory_fact_import import DEFAULT_SOURCE, validate_real_inventory


def _seed_item(repository: FactRepository, material_code: str) -> str:
    batch_id = str(uuid4())
    source_id = str(uuid4())
    item_id = str(uuid4())
    with repository.store.transaction() as connection:
        repository.store.execute(
            connection,
            "INSERT INTO import_batches "
            "(id, mapping_name, status, created_at, published_at, pending_confirmation_fields_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                "test_item_master",
                "published",
                "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
                "[]",
            ),
        )
        repository.store.execute(
            connection,
            "INSERT INTO source_files "
            "(id, import_batch_id, original_filename, content_sha256, byte_size, source_kind, "
            "source_uri, immutable_copy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                batch_id,
                "item-master-fixture.xlsx",
                "a" * 64,
                1,
                "local",
                "test://item-master",
                False,
            ),
        )
        repository.store.execute(
            connection,
            "INSERT INTO items "
            "(id, material_code, name, specification, unit, import_batch_id, source_file_id, "
            "source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                material_code,
                "测试物料",
                None,
                "件",
                batch_id,
                source_id,
                "物料主数据",
                2,
            ),
        )
    return item_id


def _create_inventory_workbook(file_path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "库存表"
    sheet.append(["归属地", "库位", "物料代码", "批次号", "库存", "不参与字段"])
    for row in rows:
        sheet.append([*row, "不得推断在途"])
    excluded = workbook.create_sheet("电阻电容现库位")
    excluded.append(["归属地", "库位", "物料代码", "批次号", "库存"])
    excluded.append(["X", "EXCLUDED", "SHOULD-NOT-IMPORT", "B-X", 999])
    workbook.save(file_path)
    workbook.close()
    return file_path


class InventoryFactImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.repository = FactRepository(SQLiteFactStore(self.temp_path / "facts.db"))
        self.repository.migrate()
        self.service = InventoryImportService(self.repository)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_multiple_batches_and_locations_are_preserved_without_aggregation(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "inventory.xlsx",
            [
                ["S1", "L1", "MAT-001", "B1", 10],
                ["S1", "L2", "MAT-001", "B2", 20],
                ["S1", "L2", "MAT-001", "B2", 20],
            ],
        )
        snapshot_at = datetime(2026, 9, 28, tzinfo=UTC)

        staged = self.service.stage_inventory(source, snapshot_at=snapshot_at)
        published = self.service.publish(staged.import_batch_id)
        queried = self.service.get_inventory_as_of(
            "MAT-001", datetime(2026, 9, 29, tzinfo=UTC)
        )

        self.assertEqual(staged.status, ImportBatchStatus.READY_TO_PUBLISH)
        self.assertEqual(staged.staged_row_count, 3)
        self.assertEqual(staged.duplicate_row_count, 1)
        self.assertEqual(published["fact_count"], 3)
        assert queried is not None
        self.assertEqual(len(queried["facts"]), 3)
        self.assertEqual({row["location"] for row in queried["facts"]}, {"L1", "L2"})
        self.assertEqual({row["batch_no"] for row in queried["facts"]}, {"B1", "B2"})
        self.assertEqual(queried["totals"]["on_hand_qty"], 50)
        self.assertIsNone(queried["totals"]["available_qty"])

    def test_invalid_quantity_and_missing_material_are_rejected_with_reasons(self) -> None:
        source = _create_inventory_workbook(
            self.temp_path / "invalid.xlsx",
            [["S1", "L1", None, "B1", 10], ["S1", "L2", "MAT-X", "B2", -1]],
        )

        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )

        self.assertEqual(staged.status, ImportBatchStatus.INVALID)
        self.assertEqual(
            {error.error_code for error in staged.errors},
            {"MATERIAL_CODE_REQUIRED", "ON_HAND_QTY_INVALID"},
        )
        with self.assertRaisesRegex(ValueError, "不能发布"):
            self.service.publish(staged.import_batch_id)
        self.assertEqual(self.service.inventory_repository.count_published_facts(), 0)

    def test_unmatched_item_is_reported_and_never_becomes_inventory_zero(self) -> None:
        source = _create_inventory_workbook(
            self.temp_path / "unmatched.xlsx",
            [["S1", "L1", "UNKNOWN-001", "B1", 0]],
        )

        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )
        report = self.service.get_quality_report(staged.import_batch_id)
        rows = self.service.inventory_repository.get_staged_rows(staged.import_batch_id)

        self.assertEqual(staged.status, ImportBatchStatus.PENDING_CONFIRMATION)
        self.assertEqual(staged.unmatched_item_count, 1)
        self.assertIn("item_mapping", staged.pending_confirmation_fields)
        assert report is not None
        self.assertEqual(report["unmatched_material_count"], 1)
        self.assertIsNone(rows[0].item_id)
        self.assertEqual(rows[0].on_hand_qty, 0)

    def test_unknown_inventory_fields_remain_none(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "unknown-fields.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )
        row = self.service.inventory_repository.get_staged_rows(staged.import_batch_id)[0]

        self.assertIsNone(row.available_qty)
        self.assertIsNone(row.reserved_qty)
        self.assertIsNone(row.warehouse)
        self.assertIsNone(row.quality_status)

    def test_source_sheet_row_hash_and_import_batch_are_traceable(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "traceable.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )
        self.service.publish(staged.import_batch_id)

        result = self.service.get_inventory_as_of(
            "MAT-001", datetime(2026, 9, 30, tzinfo=UTC)
        )

        assert result is not None
        self.assertEqual(result["snapshot"]["source_sheet"], "库存表")
        self.assertEqual(len(result["snapshot"]["content_sha256"]), 64)
        self.assertEqual(result["facts"][0]["source_row_number"], 2)
        self.assertEqual(result["facts"][0]["import_batch_id"], staged.import_batch_id)

    def test_as_of_query_uses_latest_snapshot_not_later_than_requested_time(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "as-of.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        first = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 20, tzinfo=UTC)
        )
        self.service.publish(first.import_batch_id)
        second = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 25, tzinfo=UTC)
        )
        self.service.publish(second.import_batch_id)

        before_second = self.service.get_inventory_as_of(
            "MAT-001", datetime(2026, 9, 22, tzinfo=UTC)
        )
        after_second = self.service.get_inventory_as_of(
            "MAT-001", datetime(2026, 9, 26, tzinfo=UTC)
        )

        assert before_second is not None and after_second is not None
        self.assertEqual(before_second["snapshot"]["import_batch_id"], first.import_batch_id)
        self.assertEqual(after_second["snapshot"]["import_batch_id"], second.import_batch_id)

    def test_snapshot_at_is_required_and_can_be_confirmed_explicitly(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "needs-time.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        staged = self.service.stage_inventory(source)
        self.assertEqual(staged.status, ImportBatchStatus.PENDING_CONFIRMATION)
        self.assertIn("snapshot_at", staged.pending_confirmation_fields)

        batch = self.service.confirm_snapshot_at(
            staged.import_batch_id, datetime(2026, 9, 28, tzinfo=UTC)
        )
        self.assertEqual(batch.status, ImportBatchStatus.READY_TO_PUBLISH)

    def test_explicit_item_alias_can_resolve_previous_unmatched_inventory_code(self) -> None:
        _seed_item(self.repository, "STANDARD-001")
        source = _create_inventory_workbook(
            self.temp_path / "alias.xlsx",
            [["S1", "L1", "EXTERNAL-001", "B1", 8]],
        )
        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )
        self.assertEqual(staged.status, ImportBatchStatus.PENDING_CONFIRMATION)

        self.service.inventory_repository.add_item_alias("STANDARD-001", "EXTERNAL-001")
        refreshed = self.service.refresh_item_matches(staged.import_batch_id)

        self.assertEqual(refreshed.status, ImportBatchStatus.READY_TO_PUBLISH)
        published = self.service.publish(staged.import_batch_id)
        self.assertEqual(published["fact_count"], 1)

    def test_duplicate_source_sheet_and_snapshot_publish_is_rejected_and_auditable(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "duplicate-import.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        snapshot = datetime(2026, 9, 28, tzinfo=UTC)
        first = self.service.stage_inventory(source, snapshot_at=snapshot)
        second = self.service.stage_inventory(source, snapshot_at=snapshot)
        self.service.publish(first.import_batch_id)

        with self.assertRaisesRegex(ValueError, "已发布"):
            self.service.publish(second.import_batch_id)

        second_batch = self.repository.get_import_batch(second.import_batch_id)
        assert second_batch is not None
        self.assertEqual(second_batch.status, ImportBatchStatus.READY_TO_PUBLISH)
        self.assertEqual(self.service.inventory_repository.count_published_facts(), 1)

    def test_only_confirmed_inventory_sheet_is_imported(self) -> None:
        _seed_item(self.repository, "MAT-001")
        source = _create_inventory_workbook(
            self.temp_path / "source-isolation.xlsx",
            [["S1", "L1", "MAT-001", "B1", 8]],
        )
        staged = self.service.stage_inventory(
            source, snapshot_at=datetime(2026, 9, 28, tzinfo=UTC)
        )
        rows = self.service.inventory_repository.get_staged_rows(staged.import_batch_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].sheet_name, "库存表")
        self.assertNotEqual(rows[0].raw_material_code, "SHOULD-NOT-IMPORT")


class LocalPrivateInventoryAcceptanceTests(unittest.TestCase):
    @unittest.skipUnless(
        DEFAULT_SOURCE.is_file(),
        "data/raw 私有库存工作簿不存在，跳过本地验收",
    )
    def test_real_inventory_workbook_stages_without_publishing_private_facts(self) -> None:
        result = validate_real_inventory()

        self.assertEqual(result["result"], "passed")
        self.assertEqual(result["staged_row_count"], 6710)
        self.assertEqual(result["valid_row_count"], 6710)
        self.assertEqual(result["error_count"], 0)
        self.assertFalse(result["published"])


if __name__ == "__main__":
    unittest.main()
