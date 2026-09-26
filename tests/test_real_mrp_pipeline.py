import unittest

from repositories.inventory_disposition_repository import load_inventory_dispositions
from repositories.purchase_parameter_repository import load_purchase_parameters
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from services.bom_service import explode_bom
from services.inventory_disposition_service import apply_inventory_dispositions
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

    def test_missing_inventory_is_not_automatically_converted_to_zero(self) -> None:
        scope = apply_inventory_dispositions(
            {"M-003": {"inventory_status": "missing", "stock": None}},
            {},
        )
        self.assertEqual(scope["M-003"]["inventory_status"], "missing")
        self.assertIsNone(scope["M-003"]["stock"])

    def test_confirmed_stock_zero_becomes_known_zero_inventory(self) -> None:
        scope = apply_inventory_dispositions(
            {"M-004": {"inventory_status": "missing", "stock": None}},
            {
                "M-004": {
                    "disposition": "stock_zero",
                    "confirmed_stock": 0,
                    "include_in_mrp": True,
                    "reason": "盘点确认",
                    "confirmed_by": "业务人员",
                }
            },
        )
        result = analyze_mrp({"M-004": 2}, scope)
        self.assertEqual(scope["M-004"]["inventory_status"], "known")
        self.assertEqual(result["materials"][0]["stock"], 0)
        self.assertEqual(result["materials"][0]["shortage"], 2)

    def test_purchase_to_order_keeps_bom_material_and_blocks_definitive_conclusion(self) -> None:
        requirements = explode_bom("P-001", 1, {"P-001": {"M-005": 1}})
        scope = apply_inventory_dispositions(
            {"M-005": {"inventory_status": "missing", "stock": None}},
            {"M-005": {"disposition": "purchase_to_order", "include_in_mrp": True}},
        )
        result = analyze_mrp(requirements, scope)
        self.assertEqual(requirements, {"M-005": 1})
        self.assertEqual(result["materials"][0]["business_disposition"], "purchase_to_order")
        self.assertIsNone(result["can_produce"])

    def test_bom_obsolete_only_raises_business_warning_without_deleting_bom(self) -> None:
        requirements = explode_bom("P-002", 1, {"P-002": {"M-006": 1}})
        scope = apply_inventory_dispositions(
            {"M-006": {"inventory_status": "missing", "stock": None}},
            {"M-006": {"disposition": "bom_obsolete", "include_in_mrp": False}},
        )
        result = analyze_mrp(requirements, scope)
        self.assertEqual(requirements, {"M-006": 1})
        self.assertEqual(result["materials"][0]["inventory_status"], "business_disposition")
        self.assertEqual(result["materials"][0]["business_disposition"], "bom_obsolete")

    def test_unconfirmed_template_keeps_pending_status_non_definitive(self) -> None:
        self.assertEqual(load_inventory_dispositions(), {})
        result = analyze_mrp(
            {"M-007": 1},
            {"M-007": {"inventory_status": "excluded_pending_confirmation"}},
        )
        self.assertIsNone(result["can_produce"])
        self.assertEqual(result["production_status"], "库存数据不完整")


if __name__ == "__main__":
    unittest.main()
