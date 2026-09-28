import inspect
import unittest
from uuid import uuid4
from unittest.mock import patch

from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from workflows import pmc_graph
from workflows.pmc_graph import (
    get_pmc_workflow_state,
    resume_pmc_workflow,
    route_after_production_status,
    run_pmc_workflow,
)


class PmcGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.purchase_mode_patcher = patch(
            "tools.purchase_tool.resolve_data_source_mode",
            return_value="raw",
        )
        self.purchase_mode_patcher.start()
        self.addCleanup(self.purchase_mode_patcher.stop)

    def run_real_graph(self) -> tuple[str, dict[str, object]]:
        workflow_id = f"test-{uuid4()}"
        run_pmc_workflow("KQ-Z112", "V01", 1, workflow_id)
        return workflow_id, get_pmc_workflow_state(workflow_id)

    def test_normal_graph_flow_reaches_purchase_parameter_pause(self) -> None:
        _, state = self.run_real_graph()
        self.assertEqual(state["workflow_status"], "waiting_for_purchase_parameters")
        self.assertEqual(state["production_decision"]["decision_status"], "blocked")
        self.assertEqual(len(state["missing_purchase_parameters"]), 8)
        self.assertIn("generate_report", state["completed_nodes"])

    def test_input_validation_failure_is_structured(self) -> None:
        workflow_id = f"test-{uuid4()}"
        run_pmc_workflow("KQ-Z112", "V01", 0, workflow_id)
        state = get_pmc_workflow_state(workflow_id)
        self.assertEqual(state["workflow_status"], "error")
        self.assertIn("生产数量必须为正整数", state["errors"][0])
        self.assertNotIn("bom_analysis", state["completed_nodes"])

    def test_unknown_bom_is_captured_as_bom_error(self) -> None:
        workflow_id = f"test-{uuid4()}"
        run_pmc_workflow("UNKNOWN-PRODUCT", "V01", 1, workflow_id)
        state = get_pmc_workflow_state(workflow_id)
        self.assertEqual(state["workflow_status"], "error")
        self.assertIn("bom_analysis", state["completed_nodes"])
        self.assertTrue(state["errors"])

    def test_resume_with_one_material_reuses_prior_bom_and_mrp_state(self) -> None:
        workflow_id, initial = self.run_real_graph()
        material = initial["missing_purchase_parameters"][0]["material"]
        resumed = resume_pmc_workflow(
            workflow_id,
            {material: {"supplier_code": "SUP-01", "safety_stock": 0, "lead_time_days": 3}},
        )
        self.assertEqual(resumed["workflow_status"], "waiting_for_purchase_parameters")
        self.assertEqual(len(resumed["missing_purchase_parameters"]), 7)
        self.assertEqual(resumed["completed_nodes"].count("bom_analysis"), 1)
        self.assertEqual(resumed["completed_nodes"].count("mrp_analysis"), 1)
        self.assertGreater(resumed["completed_nodes"].count("purchase_analysis"), initial["completed_nodes"].count("purchase_analysis"))

    def test_full_purchase_parameter_resume_reaches_procurement_pending(self) -> None:
        workflow_id, initial = self.run_real_graph()
        parameters = {
            item["material"]: {"supplier_code": f"SUP-{index:02d}", "safety_stock": 0, "lead_time_days": 3}
            for index, item in enumerate(initial["missing_purchase_parameters"], start=1)
        }
        state = resume_pmc_workflow(workflow_id, parameters)
        self.assertEqual(state["workflow_status"], "completed")
        self.assertEqual(state["production_decision"]["decision_status"], "procurement_pending")
        self.assertFalse(state["production_decision"]["can_start_production"])
        self.assertEqual(state["missing_purchase_parameters"], [])

    def test_ready_production_status_routes_to_report(self) -> None:
        self.assertEqual(route_after_production_status({"production_decision": {"decision_status": "ready"}}), "ready")

    def test_blocked_production_status_routes_to_report(self) -> None:
        self.assertEqual(route_after_production_status({"production_decision": {"decision_status": "blocked"}}), "blocked")

    def test_data_incomplete_production_status_routes_to_report(self) -> None:
        self.assertEqual(route_after_production_status({"production_decision": {"decision_status": "data_incomplete"}}), "data_incomplete")

    def test_mrp_tool_failure_is_captured_in_state(self) -> None:
        workflow_id = f"test-{uuid4()}"
        class FailingMrpTool:
            @staticmethod
            def invoke(_: object) -> None:
                raise RuntimeError("库存工具失败")

        with patch("workflows.pmc_graph.real_mrp_check", FailingMrpTool()):
            run_pmc_workflow("KQ-Z112", "V01", 1, workflow_id)
        state = get_pmc_workflow_state(workflow_id)
        self.assertEqual(state["workflow_status"], "error")
        self.assertIn("库存工具失败", state["errors"][0])
        self.assertIn("mrp_analysis", state["completed_nodes"])

    def test_graph_result_matches_deterministic_report_before_pause(self) -> None:
        _, state = self.run_real_graph()
        deterministic = build_kq_z112_report()
        report = state["report"]
        self.assertEqual(report["production_decision"], deterministic["production_decision"])
        self.assertEqual(report["shortage_list"], deterministic["shortage_list"])
        self.assertEqual(report["purchase_parameter_missing_items"], deterministic["purchase_parameter_missing_items"])

    def test_graph_only_orchestrates_tools_without_business_algorithms(self) -> None:
        source = inspect.getsource(pmc_graph).lower()
        self.assertNotIn("services.", source)
        self.assertNotIn("deepseek", source)
        self.assertNotIn("chatopenai", source)


if __name__ == "__main__":
    unittest.main()
