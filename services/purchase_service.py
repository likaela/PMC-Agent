"""采购建议业务计算服务。"""

from collections.abc import Mapping


def _is_nonnegative_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def assess_purchase_risks(
    shortages: Mapping[str, int],
    purchase_data: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int | str]]:
    """根据缺口和采购周期确定采购风险等级。"""
    result: dict[str, dict[str, int | str]] = {}

    for material, shortage in shortages.items():
        if (
            not isinstance(material, str)
            or not isinstance(shortage, int)
            or isinstance(shortage, bool)
            or shortage < 0
        ):
            raise ValueError("缺料数据必须为 {物料名称: 非负整数} 格式")
        if material not in purchase_data:
            raise ValueError(f"采购数据中不存在物料：{material}")

        lead_time_days = purchase_data[material].get("lead_time_days")
        if (
            not isinstance(lead_time_days, int)
            or isinstance(lead_time_days, bool)
            or lead_time_days < 0
        ):
            raise ValueError(f"物料 {material} 的采购参数无效")

        if shortage == 0:
            risk_level = "无缺料风险"
        elif lead_time_days <= 7:
            risk_level = "一般风险"
        else:
            risk_level = "高风险"
        result[material] = {
            "shortage": shortage,
            "lead_time_days": lead_time_days,
            "risk_level": risk_level,
        }

    return result


def purchase_recommendation(
    shortages: Mapping[str, int],
    purchase_data: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int | str]]:
    """根据 ``{material: shortage}`` 生成采购建议。"""
    result: dict[str, dict[str, int | str]] = {}
    risks = assess_purchase_risks(shortages, purchase_data)

    for material, shortage in shortages.items():
        if shortage == 0:
            continue

        material_info = purchase_data[material]
        safety_stock = material_info.get("safety_stock")
        lead_time_days = material_info.get("lead_time_days")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (safety_stock, lead_time_days)
        ):
            raise ValueError(f"物料 {material} 的采购参数无效")
        result[material] = {
            "shortage": shortage,
            "safety_stock": safety_stock,
            "recommended_quantity": shortage + safety_stock,
            "lead_time_days": lead_time_days,
            "risk_level": risks[material]["risk_level"],
        }

    return result


def analyze_real_purchase(
    mrp_materials: list[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    """列出需由业务人员逐项补充采购参数的已知缺料物料。"""
    recommendations: list[dict[str, object]] = []
    parameter_pending: list[dict[str, object]] = []
    required_fields = ("supplier_code", "safety_stock", "lead_time_days")

    for item in mrp_materials:
        if item.get("inventory_status") != "known" or not _is_nonnegative_number(item.get("shortage")):
            continue
        shortage = item["shortage"]
        if shortage == 0:
            continue
        material = item.get("material")
        if not isinstance(material, str):
            raise ValueError("MRP 物料格式无效")

        parameter_pending.append(
            {
                "material": material,
                "shortage": shortage,
                "data_status": "采购参数待逐项补充",
                "missing_fields": list(required_fields),
            }
        )
    return {"recommendations": recommendations, "parameter_pending": parameter_pending}
