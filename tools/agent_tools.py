from langchain.tools import tool

from .bom_tool import explode_bom
from .inventory_tool import check_inventory
from .purchase_tool import purchase_recommendation



@tool
def bom_check(product:str, quantity:int):
    """
    根据产品型号和生产数量展开BOM，
    返回所需物料数量。
    """

    result = explode_bom(
        product,
        quantity
    )

    return str(result)

@tool
def inventory_check(materials:dict):
    """
    根据BOM需求查询库存和缺料情况
    """

    result = check_inventory(
        materials
    )

    return str(result)

@tool
def purchase_check(shortages:str):
    """
    根据缺料数量生成采购建议
    """

    import ast


    shortage_dict = ast.literal_eval(
        shortages
    )


    result = purchase_recommendation(
        shortage_dict
    )


    return str(result)