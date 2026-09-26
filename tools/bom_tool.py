def explode_bom(product, quantity):

    bom_database = {

        "ABC-1000": {

            "主板":1,
            "电机":2,
            "螺丝":8

        }

    }


    if product not in bom_database:
        return "没有找到该产品BOM"


    result={}


    for material, qty in bom_database[product].items():

        result[material]=qty*quantity


    return result