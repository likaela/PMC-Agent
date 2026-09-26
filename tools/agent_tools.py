"""LangChain Tool 定义：仅负责 Agent 与业务服务之间的适配。"""

from langchain.tools import tool

from .bom_tool import explode_bom
from .inventory_tool import check_inventory
from .purchase_tool import (
    check_real_purchase_parameters,
    purchase_recommendation,
    supplement_real_purchase_parameter,
)


@tool
def bom_check(product: str, quantity: int) -> dict[str, int]:
    """根据产品型号和生产数量展开 BOM，返回 {物料: 需求数量}。"""
    return explode_bom(product, quantity)


@tool
def inventory_check(materials: dict[str, int]) -> dict[str, dict[str, int]]:
    """查询 BOM 需求的库存，返回每种物料的 stock、available、shortage。"""
    return check_inventory(materials)


@tool
def purchase_check(shortages: dict[str, int]) -> dict[str, dict[str, int | str]]:
    """根据 {物料: 缺口} 生成采购数量、安全库存和采购周期建议。"""
    return purchase_recommendation(shortages)


@tool
def real_purchase_parameter_check(shortages: dict[str, int]) -> list[dict[str, object]]:
    """针对真实 MRP 的缺料逐项检查采购参数，返回待补充字段或确定性采购建议。"""
    return check_real_purchase_parameters(shortages)


@tool
def supplement_real_purchase_parameter_check(
    material: str,
    supplier_code: str | None = None,
    safety_stock: int | None = None,
    lead_time_days: int | None = None,
) -> dict[str, object]:
    """补充一个缺料物料的采购参数；参数完整后立即重新计算采购数量和风险。"""
    return supplement_real_purchase_parameter(
        material,
        supplier_code=supplier_code,
        safety_stock=safety_stock,
        lead_time_days=lead_time_days,
    )
