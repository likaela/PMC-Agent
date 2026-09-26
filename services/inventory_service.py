"""库存与缺料计算业务服务。"""

from collections.abc import Mapping


INVENTORY_DATABASE: dict[str, int] = {
    "主板": 800,
    "电机": 3000,
    "螺丝": 20000,
}


def check_inventory(materials: Mapping[str, int]) -> dict[str, dict[str, int]]:
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

        stock = INVENTORY_DATABASE.get(material, 0)
        # 当前演示数据没有占用量或在途量，因此 available 等于 stock。
        available = stock
        result[material] = {
            "stock": stock,
            "available": available,
            "shortage": max(required_quantity - available, 0),
        }

    return result
