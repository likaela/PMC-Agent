import inspect
import unittest

from services.purchase_service import analyze_interactive_purchase, evaluate_interactive_purchase
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from tools.purchase_tool import (
    check_real_purchase_parameters,
    clear_real_purchase_parameter_session,
    supplement_real_purchase_parameter,
)


class PurchaseInteractionTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_real_purchase_parameter_session()

    def test_all_three_purchase_parameters_missing(self) -> None:
        result = evaluate_interactive_purchase("11296476B0101", 78)
        self.assertEqual(result["purchase_status"], "需要补充采购参数")
        self.assertEqual(
            result["missing_fields"],
            ["supplier_code", "safety_stock", "lead_time_days"],
        )

    def test_partial_purchase_parameters_list_only_missing_fields(self) -> None:
        result = evaluate_interactive_purchase(
            "11296476B0101", 78, {"supplier_code": "SUP-01"}
        )
        self.assertEqual(result["missing_fields"], ["safety_stock", "lead_time_days"])

    def test_complete_parameters_generate_deterministic_purchase_suggestion(self) -> None:
        result = evaluate_interactive_purchase(
            "11296476B0101",
            78,
            {"supplier_code": "SUP-01", "safety_stock": 12, "lead_time_days": 8},
        )
        self.assertEqual(result["suggested_purchase_qty"], 90)
        self.assertEqual(result["risk_level"], "高风险")

    def test_zero_safety_stock_is_valid(self) -> None:
        result = evaluate_interactive_purchase(
            "11296476B0101",
            78,
            {"supplier_code": "SUP-01", "safety_stock": 0, "lead_time_days": 7},
        )
        self.assertEqual(result["suggested_purchase_qty"], 78)
        self.assertEqual(result["risk_level"], "一般风险")

    def test_invalid_lead_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "采购提前期"):
            evaluate_interactive_purchase(
                "11296476B0101",
                78,
                {"supplier_code": "SUP-01", "safety_stock": 0, "lead_time_days": -1},
            )

    def test_invalid_partially_supplemented_lead_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "采购提前期"):
            evaluate_interactive_purchase("11296476B0101", 78, {"lead_time_days": -1})

    def test_supplement_one_material_and_recalculate_in_current_session(self) -> None:
        self.assertEqual(
            check_real_purchase_parameters({"11296476B0101": 78})[0]["purchase_status"],
            "需要补充采购参数",
        )
        partial = supplement_real_purchase_parameter("11296476B0101", supplier_code="SUP-01")
        self.assertEqual(partial["missing_fields"], ["safety_stock", "lead_time_days"])
        completed = supplement_real_purchase_parameter(
            "11296476B0101", safety_stock=5, lead_time_days=3
        )
        self.assertEqual(completed["suggested_purchase_qty"], 83)
        self.assertEqual(completed["risk_level"], "一般风险")

    def test_purchase_calculation_service_does_not_depend_on_llm(self) -> None:
        source = inspect.getsource(analyze_interactive_purchase).lower()
        self.assertNotIn("langchain", source)
        self.assertNotIn("deepseek", source)

    def test_real_kq_z112_shortages_generate_eight_parameter_pending_items(self) -> None:
        report = build_kq_z112_report()
        pending_items = report["purchase_parameter_missing_items"]
        self.assertEqual(len(pending_items), 8)
        self.assertEqual(
            {item["material"] for item in pending_items},
            {
                "11296476B0101",
                "11225339B0101",
                "11295100A2101",
                "105A710024201",
                "105A747014201",
                "14S6006202101",
                "14S0464400101",
                "14S0465000101",
            },
        )
        self.assertTrue(
            all(item["purchase_status"] == "需要补充采购参数" for item in pending_items)
        )
