"""对本机私有 3588M 工作簿执行只读 staging 验收。

文件不存在时明确输出 SKIP；脚本不发布事实、不修改源文件，也不输出 BOM 明细或价格。
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
from services.bom_import_service import BomImportService


DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raw" / "3588M 核价 终版.xls"


def validate_3588m(file_path: str | Path = DEFAULT_SOURCE) -> dict[str, object]:
    source = Path(file_path)
    if not source.is_file():
        return {
            "result": "skipped",
            "reason": "私有 3588M 文件不存在",
        }

    with tempfile.TemporaryDirectory() as directory:
        repository = FactRepository(SQLiteFactStore(Path(directory) / "facts.db"))
        repository.migrate()
        service = BomImportService(repository)
        result = service.stage_bom(source)
        rows = repository.get_staged_rows(result.import_batch_id)
        summary = {
            "result": "passed" if result.staged_row_count == 91 and result.error_count == 0 else "failed",
            "status": result.status.value,
            "staged_row_count": result.staged_row_count,
            "error_count": result.error_count,
            "pending_confirmation_fields": list(result.pending_confirmation_fields),
            "source_sheets": sorted({row.sheet_name for row in rows}),
            "parent_versions": sorted(
                {f"{row.parent_material_code}/{row.version}" for row in rows}
            ),
            "source_row_range": [
                min((row.source_row_number for row in rows), default=None),
                max((row.source_row_number for row in rows), default=None),
            ],
            "all_rows_traceable": all(
                row.source_file_id and row.sheet_name and row.source_row_number for row in rows
            ),
        }
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="只读验收 3588M BOM 事实层导入")
    parser.add_argument("--file", type=Path, default=DEFAULT_SOURCE)
    arguments = parser.parse_args()
    result = validate_3588m(arguments.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["result"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
