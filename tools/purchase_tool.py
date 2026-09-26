def purchase_recommendation(shortages):
    """
    根据缺料情况生成采购建议

    shortages:
    {
        "主板":200
    }

    """

    material_info = {

        "主板":{

            "供应周期":20,

            "安全库存":100

        },

        "电机":{

            "供应周期":15,

            "安全库存":200

        },

        "螺丝":{

            "供应周期":7,

            "安全库存":1000

        }

    }


    result={}


    for material, shortage in shortages.items():


        if shortage <=0:
            continue


        info = material_info.get(
            material,
            {}
        )


        safety_stock = info.get(
            "安全库存",
            0
        )


        lead_time = info.get(
            "供应周期",
            0
        )


        purchase_qty = (
            shortage
            +
            safety_stock
        )


        result[material]={

            "建议采购数量":
                purchase_qty,

            "缺口":
                shortage,

            "采购周期":
                lead_time,

            "安全库存":
                safety_stock

        }


    return result

if __name__=="__main__":


    test={

        "主板":200

    }


    print(
        purchase_recommendation(test)
    )