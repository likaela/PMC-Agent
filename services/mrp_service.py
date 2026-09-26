"""MRP 齐套与生产可行性计算服务。"""

from collections.abc import Mapping

from services.inventory_service import check_inventory


def analyze_mrp(
    requirements: Mapping[str, int],
    inventory_data: Mapping[str, Mapping[str, int | float]],
) -> dict[str, object]:
    """计算物料齐套明细、两种齐套率和生产可行性。"""
    if not requirements:
        raise ValueError("最终物料需求不能为空")

    inventory_result = check_inventory(requirements, inventory_data)
    materials: list[dict[str, object]] = []
    ready_material_count = 0
    fulfilled_quantity = 0
    total_required_quantity = 0
    has_zero_available_material = False

    for material, required in requirements.items():
        if (
            not isinstance(material, str)
            or not isinstance(required, int)
            or isinstance(required, bool)
            or required <= 0
        ):
            raise ValueError("最终物料需求必须为 {物料名称: 正整数} 格式")

        item = inventory_result[material]
        available = item["available"]
        shortage = item["shortage"]
        is_ready = shortage == 0
        if is_ready:
            ready_material_count += 1
        if available == 0:
            has_zero_available_material = True

        fulfilled_quantity += min(required, available)
        total_required_quantity += required
        materials.append(
            {
                "material": material,
                "required": required,
                "available": available,
                "shortage": shortage,
                "is_ready": is_ready,
            }
        )

    can_produce = ready_material_count == len(materials)
    if can_produce:
        production_status = "齐套"
    elif has_zero_available_material:
        production_status = "严重缺料"
    else:
        production_status = "部分缺料"

    return {
        "materials": materials,
        "material_readiness_rate": ready_material_count / len(materials),
        "quantity_fulfillment_rate": fulfilled_quantity / total_required_quantity,
        "can_produce": can_produce,
        "production_status": production_status,
    }
