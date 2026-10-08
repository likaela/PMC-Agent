"""Read-only KQ data readiness entry point. There is no publish or migrate option."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_kq_z112_enterprise_facts import DEFAULT_BOM, DEFAULT_INVENTORY, precheck
from services.enterprise_data_readiness_service import render_enterprise_readiness_report

DEFAULT_CONFIRMATIONS = PROJECT_ROOT / "data/normalized/kq_z112_confirmations.json"
DEFAULT_JSON = PROJECT_ROOT / "data/normalized/kq_z112_prepublication_readiness.json"
DEFAULT_MARKDOWN = PROJECT_ROOT / "data/normalized/kq_z112_prepublication_readiness.md"


def _print_report(text: str) -> None:
    # Windows redirected output may default to GBK, which cannot encode check marks.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="企业数据发布前检查（只读，不自动发布）")
    parser.add_argument("--bom", type=Path, default=DEFAULT_BOM)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--confirmations", type=Path)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    confirmations_path = args.confirmations or (DEFAULT_CONFIRMATIONS if DEFAULT_CONFIRMATIONS.is_file() else None)
    inputs = {args.bom.resolve(), args.inventory.resolve()}
    if confirmations_path:
        inputs.add(confirmations_path.resolve())
    outputs = [args.json_report.resolve(), args.markdown_report.resolve()]
    raw_root = (PROJECT_ROOT / "data/raw").resolve()
    if outputs[0] == outputs[1] or any(path in inputs or path.is_relative_to(raw_root) for path in outputs):
        parser.error("报告不得覆盖输入文件、raw 文件或彼此")
    try:
        confirmations = json.loads(confirmations_path.read_text(encoding="utf-8")) if confirmations_path else {}
        result = precheck(args.bom, args.inventory, confirmations)
        report = result["readiness_report"]
        report["publication_precheck"] = {
            "status": result["status"], "pending_confirmation_fields": result["pending_confirmation_fields"],
            "note": "仅来源预检，不检查数据库重复版本，不授权发布",
        }
        report["confirmation_file"] = confirmations_path.name if confirmations_path else None
        rendered = render_enterprise_readiness_report(report)
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        outputs[0].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs[1].write_text(rendered, encoding="utf-8")
    except (ValueError, KeyError, OSError):
        print("发布前检查未完成，请核对源文件、映射和确认信息。未执行发布。")
        return 1
    _print_report(rendered)
    return 0  # A completed report may correctly conclude that business data is insufficient.


if __name__ == "__main__":
    raise SystemExit(main())
