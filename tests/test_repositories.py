import unittest

from repositories.bom_repository import load_bom_data
from repositories.inventory_repository import load_inventory_data
from repositories.purchase_repository import load_purchase_data


class ExcelRepositoryTests(unittest.TestCase):
    def test_excel_bom_data_is_loaded(self) -> None:
        bom_data = load_bom_data()
        self.assertEqual(bom_data["ABC-1000"], {"主板": 1, "电机": 2, "螺丝": 8})

    def test_excel_inventory_data_is_loaded(self) -> None:
        inventory_data = load_inventory_data()
        self.assertEqual(
            inventory_data["主板"],
            {"stock": 800, "reserved": 0, "incoming": 0, "safety_stock": 100},
        )

    def test_excel_purchase_data_is_loaded(self) -> None:
        purchase_data = load_purchase_data()
        self.assertEqual(
            purchase_data["主板"],
            {"safety_stock": 100, "lead_time_days": 20},
        )
