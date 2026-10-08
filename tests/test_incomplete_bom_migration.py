"""Nullable BOM units migrate historical facts without changing their meaning."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from repositories.fact_store import MIGRATIONS_ROOT, SQLiteFactStore


VERSION = "009_incomplete_bom_units"


@pytest.fixture(autouse=True)
def isolate_009_migration_contract(tmp_path):
    """This suite verifies 009 itself; subsequent migrations have separate tests."""
    directory = tmp_path / "through-009" / "sqlite"
    directory.mkdir(parents=True)
    for source in (MIGRATIONS_ROOT / "sqlite").glob("*.sql"):
        if source.stem <= VERSION:
            shutil.copyfile(source, directory / source.name)
    with patch("repositories.fact_store.MIGRATIONS_ROOT", directory.parent):
        yield


def _legacy_store(tmp_path: Path) -> SQLiteFactStore:
    migrations = tmp_path / "prior-migrations" / "sqlite"
    migrations.mkdir(parents=True)
    for source in (MIGRATIONS_ROOT / "sqlite").glob("*.sql"):
        if source.name < "009_":
            shutil.copyfile(source, migrations / source.name)
    store = SQLiteFactStore(tmp_path / "facts.db")
    with patch("repositories.fact_store.MIGRATIONS_ROOT", migrations.parent):
        store.migrate()
    with store.transaction(write_lock=True) as connection:
        connection.execute(
            "INSERT INTO import_batches (id, mapping_name, status, created_at) "
            "VALUES ('old-batch', 'cost-bom', 'published', '2025-03-18T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO source_files "
            "(id, import_batch_id, original_filename, content_sha256, byte_size, source_uri) "
            "VALUES ('old-source', 'old-batch', 'cost.xlsx', ?, 10, 'project://cost.xlsx')",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO items VALUES "
            "('old-item', 'MAT-OLD', 'Old name', 'Spec', 'pcs', "
            "'old-batch', 'old-source', 'BOM', 5)"
        )
        connection.execute(
            "INSERT INTO item_revisions VALUES "
            "('old-revision', 'old-item', 'Old name', 'Spec', 'pcs', "
            "'old-batch', 'old-source', 'BOM', 5)"
        )
        connection.execute(
            "INSERT INTO bom_headers "
            "(id, parent_material_code, version, effective_from, import_batch_id, "
            "source_file_id, source_sheet, effective_to) VALUES "
            "('old-bom', 'OLD-PARENT', 'V01', '2025-03-18', 'old-batch', "
            "'old-source', 'BOM', NULL)"
        )
        connection.execute(
            "INSERT INTO bom_lines VALUES "
            "('old-line', 'old-bom', 'old-item', '2.50', 'pcs', "
            "'old-batch', 'old-source', 'BOM', 5)"
        )
        connection.execute(
            "INSERT INTO price_records "
            "(id, item_id, tax_included_unit_price, currency, effective_from, "
            "import_batch_id, source_file_id, source_sheet, source_row_number) VALUES "
            "('old-price', 'old-item', '1.25', 'CNY', '2025-03-18', "
            "'old-batch', 'old-source', 'BOM', 5)"
        )
        connection.execute(
            "INSERT INTO item_aliases VALUES "
            "('old-alias', 'old-item', 'erp', 'OLD-ALIAS', '2025-03-18T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO inventory_snapshots VALUES "
            "('old-snapshot', '2025-03-18T00:00:00Z', '2025-03-18T00:00:00Z', "
            "'old-batch', 'old-source', ?, 'Stock', '2025-03-18T00:00:00Z')",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO inventory_facts "
            "(id, inventory_snapshot_id, item_id, raw_material_code, on_hand_qty, "
            "available_qty, import_batch_id, source_file_id, source_sheet, source_row_number) "
            "VALUES ('old-stock', 'old-snapshot', 'old-item', 'MAT-OLD', '100.00', "
            "NULL, 'old-batch', 'old-source', 'Stock', 8)"
        )
        connection.execute(
            "INSERT INTO staged_bom_headers "
            "(import_batch_id, source_file_id, sheet_name, source_row_number, "
            "parent_material_code, version, price_policy, confirmations_json) VALUES "
            "('old-batch', 'old-source', 'BOM', 1, 'OLD-PARENT', 'V01', 'required', "
            "'[\"historical confirmation\"]')"
        )
    return store


def _table_rows(store: SQLiteFactStore) -> dict[str, list[tuple[object, ...]]]:
    with store.transaction() as connection:
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name != 'schema_migrations' ORDER BY name"
        ).fetchall()
        return {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for (name,) in names
        }


def test_upgrade_preserves_existing_facts_history_provenance_and_foreign_keys(tmp_path):
    store = _legacy_store(tmp_path)
    before = _table_rows(store)
    with store.transaction() as connection:
        indexes = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        ).fetchall()
        foreign_keys = {
            table: connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
            for table in before
        }

    assert store.migrate() == [VERSION]
    after = _table_rows(store)
    for table in before:
        if table == "staged_bom_headers":
            assert after[table] == [(*row, "required") for row in before[table]]
        else:
            assert after[table] == before[table], table
    with store.transaction() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        for table, expected in foreign_keys.items():
            assert connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall() == expected
        for index, sql in indexes:
            assert connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (index,)
            ).fetchone()[0] == sql


def test_nullable_units_are_stored_as_sql_null_without_defaulting(tmp_path):
    store = _legacy_store(tmp_path)
    store.migrate()
    with store.transaction(write_lock=True) as connection:
        connection.execute(
            "INSERT INTO items VALUES ('new-item', 'KQ-Z112', NULL, NULL, NULL, "
            "'old-batch', 'old-source', 'BOM', 1)"
        )
        connection.execute(
            "INSERT INTO item_revisions VALUES ('new-revision', 'new-item', NULL, "
            "NULL, NULL, 'old-batch', 'old-source', 'BOM', 1)"
        )
        connection.execute(
            "INSERT INTO bom_lines VALUES ('new-line', 'old-bom', 'new-item', '1', "
            "NULL, 'old-batch', 'old-source', 'BOM', 6)"
        )
        for table, identity in (
            ("items", "new-item"), ("item_revisions", "new-revision"), ("bom_lines", "new-line")
        ):
            assert connection.execute(
                f"SELECT unit FROM {table} WHERE id = ?", (identity,)
            ).fetchone()[0] is None


def test_migrated_import_policy_defaults_to_required_and_rejects_invalid_values(tmp_path):
    store = _legacy_store(tmp_path)
    store.migrate()
    with store.transaction() as connection:
        assert connection.execute("SELECT unit_policy FROM staged_bom_headers").fetchone()[0] == "required"
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction(write_lock=True) as connection:
            connection.execute("UPDATE staged_bom_headers SET unit_policy = 'invent_units'")
    with store.transaction(write_lock=True) as connection:
        connection.execute("UPDATE staged_bom_headers SET unit_policy = 'optional_for_structure'")
        assert connection.execute("SELECT unit_policy FROM staged_bom_headers").fetchone()[0] == "optional_for_structure"


def test_nullable_units_migration_is_idempotent(tmp_path):
    store = _legacy_store(tmp_path)
    assert store.migrate() == [VERSION]
    before = _table_rows(store)
    assert store.migrate() == []
    assert _table_rows(store) == before


def test_failed_foreign_key_check_rolls_back_rebuild_and_migration_marker(tmp_path):
    store = _legacy_store(tmp_path)
    before = _table_rows(store)
    original_split = store._split_migration

    def invalid_reference(sql):
        return [*original_split(sql), "UPDATE bom_lines SET item_id = 'missing-item'"]

    with patch.object(store, "_split_migration", side_effect=invalid_reference):
        with pytest.raises(RuntimeError, match="外键校验失败"):
            store.migrate()
    assert _table_rows(store) == before
    with store.transaction() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", (VERSION,)
        ).fetchone()[0] == 0
        assert next(row for row in connection.execute("PRAGMA table_info(items)") if row[1] == "unit")[3] == 1


def test_rebuilt_tables_keep_uniqueness_and_foreign_key_enforcement(tmp_path):
    store = _legacy_store(tmp_path)
    store.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction(write_lock=True) as connection:
            connection.execute(
                "INSERT INTO bom_lines VALUES ('duplicate', 'old-bom', 'old-item', '1', "
                "NULL, 'old-batch', 'old-source', 'BOM', 9)"
            )
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction(write_lock=True) as connection:
            connection.execute("UPDATE items SET source_file_id = 'missing-source'")
