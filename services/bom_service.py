"""BOM 展开业务计算。"""

from collections.abc import Mapping


def explode_bom(
    product: str,
    quantity: int,
    bom_data: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    """计算物料需求，返回 ``{material: required_quantity}``。"""
    if product not in bom_data:
        raise ValueError(f"没有找到产品 {product} 的 BOM")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("生产数量必须是正整数")

    return {
        material: quantity_per_unit * quantity
        for material, quantity_per_unit in bom_data[product].items()
    }
