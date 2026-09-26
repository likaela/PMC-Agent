"""LangChain Tool 定义：仅负责 Agent 与业务服务之间的适配。"""

from langchain.tools import tool

from .bom_tool import explode_bom
from .inventory_tool import check_inventory
from .purchase_tool import purchase_recommendation


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
