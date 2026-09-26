"""采购建议业务计算服务。"""

from collections.abc import Mapping


MATERIAL_INFO: dict[str, dict[str, int]] = {
    "主板": {"lead_time_days": 20, "safety_stock": 100},
    "电机": {"lead_time_days": 15, "safety_stock": 200},
    "螺丝": {"lead_time_days": 7, "safety_stock": 1000},
}


def purchase_recommendation(shortages: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """根据 ``{material: shortage}`` 生成采购建议。"""
    result: dict[str, dict[str, int]] = {}

    for material, shortage in shortages.items():
        if (
            not isinstance(material, str)
            or not isinstance(shortage, int)
            or isinstance(shortage, bool)
            or shortage < 0
        ):
            raise ValueError("缺料数据必须为 {物料名称: 非负整数} 格式")
        if shortage == 0:
            continue

        material_info = MATERIAL_INFO.get(material, {})
        safety_stock = material_info.get("safety_stock", 0)
        lead_time_days = material_info.get("lead_time_days", 0)
        result[material] = {
            "shortage": shortage,
            "safety_stock": safety_stock,
            "recommended_quantity": shortage + safety_stock,
            "lead_time_days": lead_time_days,
        }

    return result
