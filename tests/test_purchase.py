import unittest

from tools.purchase_tool import purchase_recommendation


class PurchaseToolTests(unittest.TestCase):
    def test_mainboard_shortage_includes_safety_stock(self) -> None:
        result = purchase_recommendation({"主板": 200, "电机": 0, "螺丝": 0})

        self.assertEqual(
            result,
            {
                "主板": {
                    "shortage": 200,
                    "safety_stock": 100,
                    "recommended_quantity": 300,
                    "lead_time_days": 20,
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
