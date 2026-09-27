import inspect
import unittest

from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from services.production_service import build_production_decision


def make_mrp(materials: list[dict[str, object]]) -> dict[str, object]:
    return {"materials": materials}


class ProductionDecisionTests(unittest.TestCase):
    def test_all_materials_ready_returns_ready(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-001",
                        "required": 2,
                        "available": 2,
                        "shortage": 0,
                        "inventory_status": "known",
                    }
                ]
            ),
            {"recommendations": [], "parameter_pending": []},
        )
        self.assertEqual(result["decision_status"], "ready")
        self.assertTrue(result["can_start_production"])

    def test_known_shortage_without_purchase_parameters_returns_blocked(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-001",
                        "required": 10,
                        "available": 5,
                        "shortage": 5,
                        "inventory_status": "known",
                    }
                ]
            ),
            {
                "recommendations": [],
                "parameter_pending": [
                    {
                        "material": "M-001",
                        "purchase_status": "需要补充采购参数",
                        "missing_fields": ["supplier_code", "safety_stock", "lead_time_days"],
                    }
                ],
            },
        )
        self.assertEqual(result["decision_status"], "blocked")
        self.assertFalse(result["can_start_production"])
        self.assertEqual(result["recommended_actions"][0]["action"], "补充采购参数")

    def test_known_shortage_is_a_blocker_even_without_purchase_analysis_item(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-002",
                        "required": 4,
                        "available": 3,
                        "shortage": 1,
                        "inventory_status": "known",
                    }
                ]
            ),
            {"recommendations": [], "parameter_pending": []},
        )
        self.assertEqual(result["decision_status"], "blocked")
        self.assertEqual(result["blocking_materials"][0]["material"], "M-002")

    def test_complete_purchase_parameters_still_do_not_make_production_ready(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-001",
                        "required": 10,
                        "available": 5,
                        "shortage": 5,
                        "inventory_status": "known",
                    }
                ]
            ),
            {
                "recommendations": [
                    {
                        "material": "M-001",
                        "purchase_status": "采购建议已生成",
                        "lead_time_days": 8,
                        "risk_level": "高风险",
                    }
                ],
                "parameter_pending": [],
            },
        )
        self.assertEqual(result["decision_status"], "procurement_pending")
        self.assertFalse(result["can_start_production"])
        self.assertEqual(result["recommended_actions"][0]["action"], "发起采购")

    def test_unknown_inventory_returns_data_incomplete(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-001",
                        "required": 1,
                        "available": None,
                        "shortage": None,
                        "inventory_status": "missing",
                    }
                ]
            ),
            {"recommendations": [], "parameter_pending": []},
        )
        self.assertEqual(result["decision_status"], "data_incomplete")
        self.assertIsNone(result["can_start_production"])

    def test_blocking_material_includes_shortage_ratio_and_purchase_status(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {
                        "material": "M-001",
                        "required": 8,
                        "available": 2,
                        "shortage": 6,
                        "inventory_status": "known",
                    }
                ]
            ),
            {"recommendations": [], "parameter_pending": []},
        )
        blocker = result["blocking_materials"][0]
        self.assertEqual(blocker["shortage_ratio"], 0.75)
        self.assertEqual(blocker["purchase_status"], "需要补充采购参数")

    def test_multiple_shortage_priority_is_stable_and_explainable(self) -> None:
        result = build_production_decision(
            "P-001",
            1,
            make_mrp(
                [
                    {"material": "M-LOW", "required": 10, "available": 1, "shortage": 9, "inventory_status": "known"},
                    {"material": "M-HIGH", "required": 10, "available": 5, "shortage": 5, "inventory_status": "known"},
                ]
            ),
            {
                "recommendations": [
                    {"material": "M-LOW", "purchase_status": "采购建议已生成", "lead_time_days": 3, "risk_level": "一般风险"},
                    {"material": "M-HIGH", "purchase_status": "采购建议已生成", "lead_time_days": 8, "risk_level": "高风险"},
                ],
                "parameter_pending": [],
            },
        )
        self.assertEqual([item["material"] for item in result["blocking_materials"]], ["M-HIGH", "M-LOW"])
        self.assertEqual([item["priority"] for item in result["blocking_materials"]], [1, 2])

    def test_real_report_contains_production_decision_and_eight_blockers(self) -> None:
        report = build_kq_z112_report()
        decision = report["production_decision"]
        self.assertEqual(decision["decision_status"], "blocked")
        self.assertFalse(decision["can_start_production"])
        self.assertEqual(len(decision["blocking_materials"]), 8)
        self.assertEqual(len(decision["missing_purchase_parameters"]), 8)

    def test_production_decision_service_does_not_depend_on_llm(self) -> None:
        source = inspect.getsource(build_production_decision).lower()
        self.assertNotIn("langchain", source)
        self.assertNotIn("deepseek", source)


if __name__ == "__main__":
    unittest.main()
