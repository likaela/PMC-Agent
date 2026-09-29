"""受控事实层 Repository。

Repository 只负责持久化、事务和查询；Excel 字段识别与业务校验由上层服务完成。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fact_layer.models import (
    ImportBatch,
    ImportBatchStatus,
    RowValidationError,
    SourceFile,
    StagedBomRow,
)
from repositories.fact_store import PersistentFactStore


def _new_id() -> str:
    return str(uuid4())


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _cursor_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


class FactRepository:
    """Staging 与 published facts 的唯一持久化入口。"""

    def __init__(self, store: PersistentFactStore) -> None:
        self.store = store

    def migrate(self) -> list[str]:
        return self.store.migrate()

    def create_staging_batch(
        self,
        mapping_name: str,
        original_filename: str,
        content_sha256: str,
        byte_size: int,
    ) -> tuple[ImportBatch, SourceFile]:
        batch_id = _new_id()
        source_file_id = _new_id()
        created_at = datetime.now(UTC)
        with self.store.transaction() as connection:
            self.store.execute(
                connection,
                "INSERT INTO import_batches "
                "(id, mapping_name, status, created_at, pending_confirmation_fields_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    batch_id,
                    mapping_name,
                    ImportBatchStatus.STAGING.value,
                    created_at.isoformat(),
                    "[]",
                ),
            )
            self.store.execute(
                connection,
                "INSERT INTO source_files "
                "(id, import_batch_id, original_filename, content_sha256, byte_size) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_file_id, batch_id, original_filename, content_sha256, byte_size),
            )
        return (
            ImportBatch(
                id=batch_id,
                mapping_name=mapping_name,
                status=ImportBatchStatus.STAGING,
                created_at=created_at,
            ),
            SourceFile(
                id=source_file_id,
                import_batch_id=batch_id,
                original_filename=original_filename,
                content_sha256=content_sha256,
                byte_size=byte_size,
            ),
        )

    def save_staging_result(
        self,
        batch_id: str,
        rows: list[StagedBomRow],
        errors: list[RowValidationError],
        status: ImportBatchStatus,
        pending_confirmation_fields: tuple[str, ...],
        raw_payloads: dict[str, dict[str, object]] | None = None,
    ) -> None:
        raw_payloads = raw_payloads or {}
        with self.store.transaction() as connection:
            for row in rows:
                self.store.execute(
                    connection,
                    "INSERT INTO staged_bom_rows "
                    "(id, import_batch_id, source_file_id, sheet_name, source_row_number, "
                    "parent_material_code, version, material_code, material_name, specification, "
                    "quantity, tax_included_unit_price, source_total_price, unit, currency, "
                    "effective_from, validation_status, pending_fields_json, raw_payload_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row.id,
                        row.import_batch_id,
                        row.source_file_id,
                        row.sheet_name,
                        row.source_row_number,
                        row.parent_material_code,
                        row.version,
                        row.material_code,
                        row.material_name,
                        row.specification,
                        _decimal_text(row.quantity),
                        _decimal_text(row.tax_included_unit_price),
                        _decimal_text(row.source_total_price),
                        row.unit,
                        row.currency,
                        _date_text(row.effective_from),
                        row.validation_status,
                        json.dumps(list(row.pending_fields), ensure_ascii=False),
                        json.dumps(raw_payloads.get(row.id, {}), ensure_ascii=False, default=str),
                    ),
                )
            for error in errors:
                self.store.execute(
                    connection,
                    "INSERT INTO row_validation_errors "
                    "(id, import_batch_id, source_file_id, sheet_name, source_row_number, "
                    "error_code, field_name, message, raw_value) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        error.id,
                        error.import_batch_id,
                        error.source_file_id,
                        error.sheet_name,
                        error.source_row_number,
                        error.error_code,
                        error.field_name,
                        error.message,
                        error.raw_value,
                    ),
                )
            self.store.execute(
                connection,
                "UPDATE import_batches SET status = ?, staged_row_count = ?, error_count = ?, "
                "pending_confirmation_fields_json = ? WHERE id = ?",
                (
                    status.value,
                    len(rows),
                    len(errors),
                    json.dumps(list(pending_confirmation_fields), ensure_ascii=False),
                    batch_id,
                ),
            )

    def get_import_batch(self, batch_id: str) -> ImportBatch | None:
        with self.store.transaction() as connection:
            cursor = self.store.execute(
                connection,
                "SELECT id, mapping_name, status, created_at, published_at, staged_row_count, "
                "error_count, pending_confirmation_fields_json FROM import_batches WHERE id = ?",
                (batch_id,),
            )
            rows = _cursor_dicts(cursor)
        if not rows:
            return None
        row = rows[0]
        return ImportBatch(
            id=str(row["id"]),
            mapping_name=str(row["mapping_name"]),
            status=ImportBatchStatus(str(row["status"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            published_at=(
                datetime.fromisoformat(str(row["published_at"])) if row["published_at"] else None
            ),
            staged_row_count=int(row["staged_row_count"]),
            error_count=int(row["error_count"]),
            pending_confirmation_fields=tuple(
                json.loads(str(row["pending_confirmation_fields_json"]))
            ),
        )

    def get_validation_errors(self, batch_id: str) -> list[RowValidationError]:
        with self.store.transaction() as connection:
            cursor = self.store.execute(
                connection,
                "SELECT id, import_batch_id, source_file_id, sheet_name, source_row_number, "
                "error_code, field_name, message, raw_value FROM row_validation_errors "
                "WHERE import_batch_id = ? ORDER BY source_row_number, error_code",
                (batch_id,),
            )
            rows = _cursor_dicts(cursor)
        return [
            RowValidationError(
                id=str(row["id"]),
                import_batch_id=str(row["import_batch_id"]),
                source_file_id=str(row["source_file_id"]),
                sheet_name=str(row["sheet_name"]) if row["sheet_name"] is not None else None,
                source_row_number=(
                    int(row["source_row_number"]) if row["source_row_number"] is not None else None
                ),
                error_code=str(row["error_code"]),
                field_name=str(row["field_name"]) if row["field_name"] is not None else None,
                message=str(row["message"]),
                raw_value=str(row["raw_value"]) if row["raw_value"] is not None else None,
            )
            for row in rows
        ]

    def get_staged_rows(self, batch_id: str) -> list[StagedBomRow]:
        with self.store.transaction() as connection:
            cursor = self.store.execute(
                connection,
                "SELECT id, import_batch_id, source_file_id, sheet_name, source_row_number, "
                "parent_material_code, version, material_code, material_name, specification, "
                "quantity, tax_included_unit_price, source_total_price, unit, currency, "
                "effective_from, validation_status, pending_fields_json "
                "FROM staged_bom_rows WHERE import_batch_id = ? "
                "ORDER BY sheet_name, source_row_number",
                (batch_id,),
            )
            rows = _cursor_dicts(cursor)
        return [
            StagedBomRow(
                id=str(row["id"]),
                import_batch_id=str(row["import_batch_id"]),
                source_file_id=str(row["source_file_id"]),
                sheet_name=str(row["sheet_name"]),
                source_row_number=int(row["source_row_number"]),
                parent_material_code=(
                    str(row["parent_material_code"])
                    if row["parent_material_code"] is not None
                    else None
                ),
                version=str(row["version"]) if row["version"] is not None else None,
                material_code=(
                    str(row["material_code"]) if row["material_code"] is not None else None
                ),
                material_name=(
                    str(row["material_name"]) if row["material_name"] is not None else None
                ),
                specification=(
                    str(row["specification"]) if row["specification"] is not None else None
                ),
                quantity=Decimal(str(row["quantity"])) if row["quantity"] is not None else None,
                tax_included_unit_price=(
                    Decimal(str(row["tax_included_unit_price"]))
                    if row["tax_included_unit_price"] is not None
                    else None
                ),
                source_total_price=(
                    Decimal(str(row["source_total_price"]))
                    if row["source_total_price"] is not None
                    else None
                ),
                unit=str(row["unit"]) if row["unit"] is not None else None,
                currency=str(row["currency"]) if row["currency"] is not None else None,
                effective_from=(
                    date.fromisoformat(str(row["effective_from"]))
                    if row["effective_from"] is not None
                    else None
                ),
                validation_status=str(row["validation_status"]),
                pending_fields=tuple(json.loads(str(row["pending_fields_json"]))),
            )
            for row in rows
        ]

    def apply_confirmations(
        self,
        batch_id: str,
        confirmations: dict[str, object],
        material_code: str | None = None,
    ) -> ImportBatch:
        """把业务人员明确提供的值写入 staging，不生成任何默认值。"""
        allowed = {"unit", "currency", "effective_from"}
        unknown_fields = set(confirmations) - allowed
        if unknown_fields:
            raise ValueError(f"不支持的确认字段：{', '.join(sorted(unknown_fields))}")

        assignments: list[str] = []
        params: list[object] = []
        for field_name in ("unit", "currency", "effective_from"):
            if field_name not in confirmations:
                continue
            value = confirmations[field_name]
            if field_name == "effective_from":
                if isinstance(value, date):
                    value = value.isoformat()
                else:
                    value = date.fromisoformat(str(value)).isoformat()
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须由业务人员提供非空值")
            assignments.append(f"{field_name} = ?")
            params.append(value.strip() if isinstance(value, str) else value)

        if not assignments:
            batch = self.get_import_batch(batch_id)
            if batch is None:
                raise KeyError("导入批次不存在")
            return batch

        where = "import_batch_id = ? AND validation_status = 'valid'"
        params.append(batch_id)
        if material_code is not None:
            where += " AND material_code = ?"
            params.append(material_code)

        with self.store.transaction() as connection:
            cursor = self.store.execute(
                connection,
                f"UPDATE staged_bom_rows SET {', '.join(assignments)} WHERE {where}",
                params,
            )
            if cursor.rowcount == 0:
                raise KeyError("未找到可确认的暂存 BOM 行")
            remaining_cursor = self.store.execute(
                connection,
                "SELECT id, unit, currency, effective_from FROM staged_bom_rows "
                "WHERE import_batch_id = ? AND validation_status = 'valid'",
                (batch_id,),
            )
            remaining_rows = remaining_cursor.fetchall()
            pending_set: set[str] = set()
            for remaining_row in remaining_rows:
                row_pending = [
                    field_name
                    for index, field_name in enumerate(("unit", "currency", "effective_from"), 1)
                    if remaining_row[index] is None or str(remaining_row[index]).strip() == ""
                ]
                pending_set.update(row_pending)
                self.store.execute(
                    connection,
                    "UPDATE staged_bom_rows SET pending_fields_json = ? WHERE id = ?",
                    (json.dumps(row_pending, ensure_ascii=False), remaining_row[0]),
                )
            pending = sorted(pending_set)
            next_status = (
                ImportBatchStatus.PENDING_CONFIRMATION
                if pending
                else ImportBatchStatus.READY_TO_PUBLISH
            )
            self.store.execute(
                connection,
                "UPDATE import_batches SET status = ?, pending_confirmation_fields_json = ? "
                "WHERE id = ? AND error_count = 0",
                (next_status.value, json.dumps(pending, ensure_ascii=False), batch_id),
            )

        batch = self.get_import_batch(batch_id)
        if batch is None:
            raise KeyError("导入批次不存在")
        return batch

    def publish_batch(self, batch_id: str) -> dict[str, object]:
        """在一个事务中把已确认 staging 发布为不可分割的 BOM 事实。"""
        batch = self.get_import_batch(batch_id)
        if batch is None:
            raise KeyError("导入批次不存在")
        if batch.status != ImportBatchStatus.READY_TO_PUBLISH:
            raise ValueError("导入批次尚未通过校验和人工确认，不能发布")
        rows = self.get_staged_rows(batch_id)
        if not rows or any(row.validation_status != "valid" for row in rows):
            raise ValueError("导入批次没有可发布的完整 BOM 明细")

        parent_versions = {(row.parent_material_code, row.version) for row in rows}
        if len(parent_versions) != 1:
            raise ValueError("一个导入批次只能发布一个父件和版本")
        parent_material_code, version = next(iter(parent_versions))
        if not parent_material_code or not version:
            raise ValueError("父件或版本未确认")

        header_id = _new_id()
        with self.store.transaction() as connection:
            existing_cursor = self.store.execute(
                connection,
                "SELECT id FROM bom_headers WHERE parent_material_code = ? AND version = ?",
                (parent_material_code, version),
            )
            if existing_cursor.fetchone() is not None:
                raise ValueError("该父件和版本已发布，不能覆盖受控事实")

            first = rows[0]
            if first.effective_from is None:
                raise ValueError("生效日期尚未确认")
            self.store.execute(
                connection,
                "INSERT INTO bom_headers "
                "(id, parent_material_code, version, effective_from, import_batch_id, "
                "source_file_id, source_sheet) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    header_id,
                    parent_material_code,
                    version,
                    first.effective_from.isoformat(),
                    batch_id,
                    first.source_file_id,
                    first.sheet_name,
                ),
            )

            for row in rows:
                if (
                    row.material_code is None
                    or row.quantity is None
                    or row.tax_included_unit_price is None
                    or row.unit is None
                    or row.currency is None
                    or row.effective_from is None
                ):
                    raise ValueError("暂存行仍存在未确认字段")
                proposed_item_id = _new_id()
                self.store.execute(
                    connection,
                    "INSERT INTO items "
                    "(id, material_code, name, specification, unit, import_batch_id, source_file_id, "
                    "source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(material_code) DO UPDATE SET "
                    "name = excluded.name, specification = excluded.specification, unit = excluded.unit, "
                    "import_batch_id = excluded.import_batch_id, source_file_id = excluded.source_file_id, "
                    "source_sheet = excluded.source_sheet, source_row_number = excluded.source_row_number",
                    (
                        proposed_item_id,
                        row.material_code,
                        row.material_name,
                        row.specification,
                        row.unit,
                        batch_id,
                        row.source_file_id,
                        row.sheet_name,
                        row.source_row_number,
                    ),
                )
                item_cursor = self.store.execute(
                    connection,
                    "SELECT id FROM items WHERE material_code = ?",
                    (row.material_code,),
                )
                item_id = str(item_cursor.fetchone()[0])
                self.store.execute(
                    connection,
                    "INSERT INTO bom_lines "
                    "(id, bom_header_id, item_id, quantity, unit, import_batch_id, source_file_id, "
                    "source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id(),
                        header_id,
                        item_id,
                        _decimal_text(row.quantity),
                        row.unit,
                        batch_id,
                        row.source_file_id,
                        row.sheet_name,
                        row.source_row_number,
                    ),
                )
                self.store.execute(
                    connection,
                    "INSERT INTO price_records "
                    "(id, item_id, tax_included_unit_price, currency, effective_from, import_batch_id, "
                    "source_file_id, source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id(),
                        item_id,
                        _decimal_text(row.tax_included_unit_price),
                        row.currency,
                        row.effective_from.isoformat(),
                        batch_id,
                        row.source_file_id,
                        row.sheet_name,
                        row.source_row_number,
                    ),
                )

            published_at = datetime.now(UTC).isoformat()
            self.store.execute(
                connection,
                "UPDATE import_batches SET status = ?, published_at = ? WHERE id = ?",
                (ImportBatchStatus.PUBLISHED.value, published_at, batch_id),
            )

        return {
            "import_batch_id": batch_id,
            "bom_header_id": header_id,
            "parent_material_code": parent_material_code,
            "version": version,
            "line_count": len(rows),
            "status": ImportBatchStatus.PUBLISHED.value,
        }

    def get_published_bom(self, parent_material_code: str, version: str) -> dict[str, object] | None:
        with self.store.transaction() as connection:
            header_cursor = self.store.execute(
                connection,
                "SELECT h.id, h.parent_material_code, h.version, h.effective_from, h.import_batch_id, "
                "sf.original_filename, h.source_sheet "
                "FROM bom_headers h JOIN source_files sf ON sf.id = h.source_file_id "
                "WHERE h.parent_material_code = ? AND h.version = ?",
                (parent_material_code, version),
            )
            headers = _cursor_dicts(header_cursor)
            if not headers:
                return None
            header = headers[0]
            line_cursor = self.store.execute(
                connection,
                "SELECT i.material_code, i.name AS material_name, i.specification, bl.quantity, "
                "bl.unit, pr.tax_included_unit_price, pr.currency, pr.effective_from, "
                "sf.original_filename AS source_file, bl.source_sheet, bl.source_row_number, "
                "bl.import_batch_id "
                "FROM bom_lines bl JOIN items i ON i.id = bl.item_id "
                "JOIN source_files sf ON sf.id = bl.source_file_id "
                "JOIN price_records pr ON pr.item_id = bl.item_id "
                "AND pr.import_batch_id = bl.import_batch_id "
                "AND pr.source_row_number = bl.source_row_number "
                "WHERE bl.bom_header_id = ? ORDER BY bl.source_sheet, bl.source_row_number",
                (header["id"],),
            )
            lines = _cursor_dicts(line_cursor)

        for line in lines:
            line["quantity"] = Decimal(str(line["quantity"]))
            line["tax_included_unit_price"] = Decimal(str(line["tax_included_unit_price"]))
        return {
            "header": {
                "id": str(header["id"]),
                "parent_material_code": str(header["parent_material_code"]),
                "version": str(header["version"]),
                "effective_from": str(header["effective_from"]),
                "import_batch_id": str(header["import_batch_id"]),
                "source_file": str(header["original_filename"]),
                "source_sheet": str(header["source_sheet"]),
            },
            "lines": lines,
        }

    def count_published_bom_headers(self) -> int:
        with self.store.transaction() as connection:
            cursor = self.store.execute(connection, "SELECT COUNT(*) FROM bom_headers")
            return int(cursor.fetchone()[0])


__all__ = ["FactRepository"]
