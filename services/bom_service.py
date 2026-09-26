"""BOM 展开业务计算。"""


BOM_DATABASE: dict[str, dict[str, int]] = {
    "ABC-1000": {"主板": 1, "电机": 2, "螺丝": 8}
}


def explode_bom(product: str, quantity: int) -> dict[str, int]:
    """计算物料需求，返回 ``{material: required_quantity}``。"""
    if product not in BOM_DATABASE:
        raise ValueError(f"没有找到产品 {product} 的 BOM")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("生产数量必须是正整数")

    return {
        material: quantity_per_unit * quantity
        for material, quantity_per_unit in BOM_DATABASE[product].items()
    }
