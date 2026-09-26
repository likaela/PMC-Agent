import unittest

from repositories.purchase_parameter_repository import load_purchase_parameters
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from services.mrp_service import analyze_mrp
from services.purchase_service import analyze_real_purchase
from services.report_service import build_pmc_report


class RealMrpPipelineTests(unittest.TestCase):
    def test_known_zero_and_missing_inventory_are_distinct(self) -> None:
        result = analyze_mrp(
            {"已知零库存": 3, "库存缺失": 3},
            {
                "已知零库存": {
                    "inventory_status": "known",
                    "stock": 0,
                    "reserved": 0,
                    "incoming": 0,
                },
                "库存缺失": {"inventory_status": "missing"},
            },
        )
        known, missing = result["materials"]
        self.assertEqual((known["stock"], known["available"], known["shortage"]), (0, 0, 3))
        self.assertEqual((missing["stock"], missing["available"], missing["shortage"]), (None, None, None))
        self.assertEqual(missing["inventory_status"], "missing")

    def test_excluded_pending_confirmation_is_not_an_available_quantity(self) -> None:
        result = analyze_mrp(
            {"待确认料": 5},
            {"待确认料": {"inventory_status": "excluded_pending_confirmation"}},
        )
        self.assertEqual(result["materials"][0]["inventory_status"], "excluded_pending_confirmation")
        self.assertIsNone(result["materials"][0]["available"])
        self.assertEqual(result["pending_confirmation_count"], 1)

    def test_unknown_inventory_prevents_a_definitive_production_conclusion(self) -> None:
        result = analyze_mrp(
            {"已知料": 1, "未知料": 1},
            {
                "已知料": {"inventory_status": "known", "stock": 1, "reserved": 0, "incoming": 0},
                "未知料": {"inventory_status": "missing"},
            },
        )
        self.assertIsNone(result["can_produce"])
        self.assertEqual(result["production_status"], "库存数据不完整")
        self.assertEqual(result["unknown_inventory_count"], 1)

    def test_complete_purchase_parameters_generate_deterministic_advice(self) -> None:
        analysis = analyze_real_purchase(
            [{"material": "M-001", "inventory_status": "known", "shortage": 12}],
            {
                "M-001": {
                    "supplier_code": "S-001",
                    "safety_stock": 3,
                    "lead_time_days": 8,
                    "missing_fields": [],
                }
            },
        )
        self.assertEqual(
            analysis["recommendations"],
            [
                {
                    "material": "M-001",
                    "shortage": 12,
                    "safety_stock": 3,
                    "suggested_purchase_qty": 15,
                    "supplier_code": "S-001",
                    "lead_time_days": 8,
                    "risk_level": "高风险",
                    "data_status": "采购参数完整",
                }
            ],
        )

    def test_missing_purchase_parameters_are_explicit(self) -> None:
        analysis = analyze_real_purchase(
            [{"material": "M-002", "inventory_status": "known", "shortage": 2}],
            {},
        )
        self.assertEqual(analysis["recommendations"], [])
        self.assertEqual(analysis["parameter_pending"][0]["data_status"], "采购参数待补充")
        self.assertEqual(
            analysis["parameter_pending"][0]["missing_fields"],
            ["supplier_code", "safety_stock", "lead_time_days"],
        )

    def test_empty_real_purchase_template_is_not_assumed_to_have_parameters(self) -> None:
        self.assertEqual(load_purchase_parameters(), {})

    def test_real_kq_z112_pipeline_and_report_data_limitations(self) -> None:
        report = build_kq_z112_report()
        self.assertEqual(report["product_information"], {"product": "KQ-Z112", "production_quantity": 1})
        self.assertEqual(report["bom_version"], "V01")
        self.assertEqual(report["bom_material_count"], 66)
        self.assertEqual(report["inventory_data_integrity"]["known_material_count"], 44)
        self.assertEqual(report["inventory_data_integrity"]["missing_inventory_count"], 5)
        self.assertEqual(report["inventory_data_integrity"]["pending_confirmation_count"], 17)
        self.assertIsNone(report["production_feasibility"]["can_produce"])
        self.assertIn("一期可用库存仅来自主库存表", report["data_limitations_and_assumptions"][0])


if __name__ == "__main__":
    unittest.main()
