import unittest

from tools.inventory_tool import check_inventory


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


if __name__ == "__main__":
    unittest.main()
