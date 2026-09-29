"""对本机私有库存工作簿执行只读 staging 验收。

脚本使用临时 SQLite 库，不发布库存事实、不修改源文件、不输出料号或库存明细。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.inventory_import_service import InventoryImportService


DEFAULT_SOURCE = (
    PROJECT_ROOT / "data" / "raw" / "2026年库存表+料号查询表及成品库存表(1).xlsx"
)


def validate_real_inventory(file_path: str | Path = DEFAULT_SOURCE) -> dict[str, object]:
    source = Path(file_path)
    if not source.is_file():
        return {"result": "skipped", "reason": "私有库存工作簿不存在"}

    with tempfile.TemporaryDirectory() as directory:
        repository = FactRepository(SQLiteFactStore(Path(directory) / "facts.db"))
        repository.migrate()
        service = InventoryImportService(repository)
        result = service.stage_inventory(source)
        quality = service.get_quality_report(result.import_batch_id) or {}
        passed = (
            result.staged_row_count == 6710
            and result.valid_row_count == 6710
            and result.error_count == 0
            and quality.get("unique_material_count") == 4930
            and quality.get("batch_count") == 2282
            and quality.get("location_count") == 1166
        )
        return {
            "result": "passed" if passed else "failed",
            "status": result.status.value,
            "import_batch_id": result.import_batch_id,
            "staged_row_count": result.staged_row_count,
            "valid_row_count": result.valid_row_count,
            "error_count": result.error_count,
            "matched_item_count": result.matched_item_count,
            "unmatched_item_count": result.unmatched_item_count,
            "pending_confirmation_fields": list(result.pending_confirmation_fields),
            "quality_report": quality,
            "source_mutated": False,
            "published": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读验收真实库存事实 staging")
    parser.add_argument("--file", type=Path, default=DEFAULT_SOURCE)
    arguments = parser.parse_args()
    result = validate_real_inventory(arguments.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["result"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
