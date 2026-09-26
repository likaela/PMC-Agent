"""供 Agent 调用的采购工具适配层。"""

from collections.abc import Mapping

from repositories.purchase_repository import load_purchase_data
from services.purchase_service import purchase_recommendation as calculate_purchase


def purchase_recommendation(shortages: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """读取采购参数并生成采购建议。"""
    return calculate_purchase(shortages, load_purchase_data())


__all__ = ["purchase_recommendation"]
