import unittest

from tools.purchase_tool import purchase_recommendation
from services.purchase_service import assess_purchase_risks


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
                    "risk_level": "高风险",
                }
            },
        )

    def test_purchase_risk_levels_are_deterministic(self) -> None:
        result = assess_purchase_risks(
            {"快料": 5, "慢料": 5, "无缺料": 0},
            {
                "快料": {"safety_stock": 0, "lead_time_days": 7},
                "慢料": {"safety_stock": 0, "lead_time_days": 8},
                "无缺料": {"safety_stock": 0, "lead_time_days": 30},
            },
        )

        self.assertEqual(result["快料"]["risk_level"], "一般风险")
        self.assertEqual(result["慢料"]["risk_level"], "高风险")
        self.assertEqual(result["无缺料"]["risk_level"], "无缺料风险")


if __name__ == "__main__":
    unittest.main()
