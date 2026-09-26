import unittest

from services.mrp_service import analyze_mrp


class MrpServiceTests(unittest.TestCase):
    def test_all_materials_ready_has_full_kit_rates(self) -> None:
        result = analyze_mrp(
            {"主板": 100, "电机": 200},
            {
                "主板": {"stock": 100, "reserved": 0, "incoming": 0, "safety_stock": 0},
                "电机": {"stock": 300, "reserved": 0, "incoming": 0, "safety_stock": 0},
            },
        )

        self.assertEqual(result["material_readiness_rate"], 1.0)
        self.assertEqual(result["quantity_fulfillment_rate"], 1.0)
        self.assertTrue(result["can_produce"])
        self.assertEqual(result["production_status"], "齐套")

    def test_partial_shortage_has_two_kit_rates(self) -> None:
        result = analyze_mrp(
            {"主板": 100, "电机": 100},
            {
                "主板": {"stock": 50, "reserved": 0, "incoming": 0, "safety_stock": 0},
                "电机": {"stock": 100, "reserved": 0, "incoming": 0, "safety_stock": 0},
            },
        )

        self.assertEqual(result["material_readiness_rate"], 0.5)
        self.assertEqual(result["quantity_fulfillment_rate"], 0.75)
        self.assertFalse(result["can_produce"])
        self.assertEqual(result["production_status"], "部分缺料")
        self.assertEqual(result["materials"][0]["shortage"], 50)

    def test_reserved_and_incoming_affect_mrp(self) -> None:
        result = analyze_mrp(
            {"传感器": 150},
            {
                "传感器": {"stock": 100, "reserved": 20, "incoming": 50, "safety_stock": 0},
            },
        )

        self.assertEqual(
            result["materials"],
            [{"material": "传感器", "required": 150, "available": 130, "shortage": 20, "is_ready": False}],
        )
