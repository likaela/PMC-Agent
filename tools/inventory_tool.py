def check_inventory(materials):
    """
    查询库存

    materials:
    {
        "主板":1000,
        "电机":2000
    }

    返回库存情况
    """


    inventory_database = {

        "主板":800,

        "电机":3000,

        "螺丝":20000

    }


    result={}


    for material, demand in materials.items():


    # 防止AI传入列表
        if isinstance(demand, list):

            demand = demand[0]


    # 防止AI传入字符串数字
    if isinstance(demand, str):

        demand = int(demand)


    stock = inventory_database.get(
        material,
        0
    )


    shortage = demand - stock


    result[material]={

        "需求数量": demand,

        "库存数量": stock,

        "缺料数量": max(shortage,0)

    }


    return result

if __name__=="__main__":


    test={

        "主板":1000,

        "电机":2000,

        "螺丝":8000

    }


    print(
        check_inventory(test)
    )