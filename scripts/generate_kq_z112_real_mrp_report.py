"""生成 KQ-Z112 / V01 的真实数据驱动 PMC 报告，不调用外部 API。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories.purchase_parameter_repository import load_purchase_parameters
from repositories.real_bom_repository import load_real_bom_data, load_real_bom_relationships
from repositories.real_inventory_repository import build_real_inventory_scope
from services.bom_service import explode_bom
from services.mrp_service import analyze_mrp
from services.purchase_service import analyze_real_purchase
from services.report_service import build_pmc_report, render_pmc_report_markdown


PRODUCT = "KQ-Z112"
BOM_VERSION = "V01"
PRODUCTION_QUANTITY = 1
JSON_OUTPUT = PROJECT_ROOT / "data" / "normalized" / "kq_z112_real_mrp_report.json"
MARKDOWN_OUTPUT = PROJECT_ROOT / "docs" / "kq_z112_real_mrp_report.md"


def build_kq_z112_report(production_quantity: int = PRODUCTION_QUANTITY) -> dict[str, object]:
    """构建完整离线业务链的结构化结果。"""
    bom_payload = load_real_bom_relationships(
        expected_parent_material=PRODUCT,
        expected_version=BOM_VERSION,
    )
    bom_requirements = explode_bom(PRODUCT, production_quantity, load_real_bom_data())
    inventory_scope = build_real_inventory_scope(bom_requirements)
    mrp_result = analyze_mrp(bom_requirements, inventory_scope)
    purchase_analysis = analyze_real_purchase(mrp_result["materials"], load_purchase_parameters())
    return build_pmc_report(
        product=PRODUCT,
        bom_version=str(bom_payload["version"]),
        production_quantity=production_quantity,
        bom_requirements=bom_requirements,
        mrp_result=mrp_result,
        purchase_analysis=purchase_analysis,
        data_quality_status={
            "source_policy": "一期可用库存仅使用主库存表；电阻电容现库位仅标记待确认",
            "reserved": 0,
            "incoming": 0,
            "purchase_parameter_source": "material_purchase_parameters.xlsx",
        },
    )


def write_kq_z112_report() -> dict[str, object]:
    """将结构化 JSON 与人工阅读 Markdown 写入指定输出路径。"""
    report = build_kq_z112_report()
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_OUTPUT.write_text(render_pmc_report_markdown(report), encoding="utf-8")
    return report


if __name__ == "__main__":
    generated = write_kq_z112_report()
    print(
        "KQ-Z112 真实 PMC 报告已生成："
        f"已知库存 {generated['inventory_data_integrity']['known_material_count']}，"
        f"库存未知 {generated['inventory_data_integrity']['unknown_inventory_count']}。"
    )
