"""库存与缺料计算业务服务。"""

from collections.abc import Mapping


def check_inventory(
    materials: Mapping[str, int],
    inventory_data: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    """计算库存可用量和缺口，返回 ``{material: {stock, available, shortage}}``。"""
    result: dict[str, dict[str, int]] = {}

    for material, required_quantity in materials.items():
        if (
            not isinstance(material, str)
            or not isinstance(required_quantity, int)
            or isinstance(required_quantity, bool)
            or required_quantity < 0
        ):
            raise ValueError("物料需求必须为 {物料名称: 非负整数} 格式")

        if material not in inventory_data:
            raise ValueError(f"库存数据中不存在物料：{material}")

        item = inventory_data[material]
        stock = item.get("stock")
        reserved = item.get("reserved")
        incoming = item.get("incoming")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (stock, reserved, incoming)
        ):
            raise ValueError(f"物料 {material} 的库存数据无效")

        available = stock - reserved + incoming
        result[material] = {
            "stock": stock,
            "available": available,
            "shortage": max(required_quantity - available, 0),
        }

    return result
