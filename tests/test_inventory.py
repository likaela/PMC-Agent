import unittest

from tools.inventory_tool import check_inventory
from services.inventory_service import check_inventory as calculate_inventory


class InventoryToolTests(unittest.TestCase):
    def test_all_bom_materials_are_processed(self) -> None:
        result = check_inventory({"主板": 1000, "电机": 2000, "螺丝": 8000})

        self.assertEqual(
            result,
            {
                "主板": {"stock": 800, "available": 800, "shortage": 200},
                "电机": {"stock": 3000, "available": 3000, "shortage": 0},
                "螺丝": {"stock": 20000, "available": 20000, "shortage": 0},
            },
        )

    def test_unknown_material_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "库存数据中不存在物料"):
            check_inventory({"未知物料": 1})

    def test_reserved_and_incoming_change_available_quantity(self) -> None:
        result = calculate_inventory(
            {"传感器": 150},
            {
                "传感器": {
                    "stock": 100,
                    "reserved": 20,
                    "incoming": 50,
                    "safety_stock": 10,
                }
            },
        )

        self.assertEqual(
            result["传感器"],
            {"stock": 100, "available": 130, "shortage": 20},
        )


if __name__ == "__main__":
    unittest.main()
