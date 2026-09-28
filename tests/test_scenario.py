import copy
import unittest

from services.scenario_service import simulate_production_scenarios


class ScenarioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[int] = []

    def workflow_runner(self, product: str, bom_version: str, quantity: int) -> dict[str, object]:
        self.calls.append(quantity)
        is_ready = quantity <= 50
        blockers = [] if is_ready else [{"material": "M-001"}, {"material": "M-002"}]
        return {
            "workflow_id": f"workflow-{quantity}",
            "workflow_status": "completed" if is_ready else "waiting_for_purchase_parameters",
            "decision_status": "ready" if is_ready else "blocked",
            "can_start_production": is_ready,
            "blocking_materials": blockers,
            "missing_purchase_parameters": [] if is_ready else [{"material": "M-001"}],
            "report": {"quantity": quantity},
        }

    def test_original_result_is_preserved_and_reduction_recalculates(self) -> None:
        original_before = self.workflow_runner("KQ-Z112", "V01", 100)
        self.calls.clear()
        result = simulate_production_scenarios("KQ-Z112", "V01", 100, self.workflow_runner)

        self.assertEqual(self.calls, [100, 50])
        self.assertEqual(result["original_result"], original_before)
        self.assertEqual(result["scenarios"][0]["quantity"], 50)
        self.assertEqual(result["scenarios"][0]["workflow_result"]["decision_status"], "ready")

    def test_multiple_scenarios_include_conditional_purchase_plan(self) -> None:
        result = simulate_production_scenarios("KQ-Z112", "V01", 100, self.workflow_runner)

        self.assertEqual(len(result["scenarios"]), 2)
        self.assertEqual(result["scenarios"][0]["scenario_status"], "recalculated")
        purchase_plan = result["scenarios"][1]
        self.assertEqual(purchase_plan["scenario_status"], "conditional_purchase_plan")
        self.assertEqual(purchase_plan["conditional_next_status"], "procurement_pending")

    def test_single_unit_does_not_create_duplicate_reduction_scenario(self) -> None:
        result = simulate_production_scenarios("KQ-Z112", "V01", 1, self.workflow_runner)

        self.assertEqual(self.calls, [1])
        self.assertEqual(len(result["scenarios"]), 1)
        self.assertEqual(result["scenarios"][0]["scenario_status"], "conditional_purchase_plan")

    def test_service_does_not_mutate_workflow_result(self) -> None:
        result_before = self.workflow_runner("KQ-Z112", "V01", 100)
        expected = copy.deepcopy(result_before)
        self.calls.clear()
        result = simulate_production_scenarios("KQ-Z112", "V01", 100, self.workflow_runner)

        self.assertEqual(result_before, expected)
        self.assertEqual(result["original_result"], expected)


if __name__ == "__main__":
    unittest.main()
