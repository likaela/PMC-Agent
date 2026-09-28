"""Demo 合成采购参数与 raw 人工补参边界。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from repositories.demo_purchase_parameter_repository import load_demo_purchase_parameters
from tools.purchase_tool import analyze_real_purchase_for_mrp, clear_real_purchase_parameter_session
from workflows.pmc_graph import get_pmc_workflow_state, run_pmc_workflow


class DemoPurchaseParameterTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_real_purchase_parameter_session()

    def tearDown(self) -> None:
        clear_real_purchase_parameter_session()

    def test_demo_purchase_parameters_are_explicit_and_complete(self) -> None:
        parameters = load_demo_purchase_parameters()

        self.assertEqual(len(parameters), 8)
        self.assertEqual(set(parameters["DEMO-M001"]), {"supplier_code", "safety_stock", "lead_time_days"})
        self.assertEqual(parameters["DEMO-M001"]["supplier_code"], "DEMO-SUP-001")
        self.assertEqual(parameters["DEMO-M001"]["safety_stock"], 0)
        self.assertEqual(parameters["DEMO-M001"]["lead_time_days"], 3)

    def test_demo_workflow_completes_without_purchase_parameter_wait(self) -> None:
        workflow_id = f"demo-purchase-{uuid4()}"
        with patch.dict(os.environ, {"PMC_DATA_SOURCE": "demo"}):
            run_pmc_workflow("KQ-Z112", "V01", 100, workflow_id)
            state = get_pmc_workflow_state(workflow_id)

        self.assertEqual(state["workflow_status"], "completed")
        self.assertEqual(state["missing_purchase_parameters"], [])
        self.assertEqual(state["production_decision"]["decision_status"], "procurement_pending")
        self.assertFalse(state["production_decision"]["can_start_production"])
        self.assertEqual(len(state["production_decision"]["blocking_materials"]), 8)
        self.assertEqual(len(state["purchase_analysis"]["recommendations"]), 8)
        self.assertNotIn("wait_for_purchase_parameters", state["completed_nodes"])

    def test_auto_fallback_to_demo_also_uses_synthetic_purchase_parameters(self) -> None:
        workflow_id = f"demo-auto-purchase-{uuid4()}"
        with (
            patch.dict(os.environ, {"PMC_DATA_SOURCE": "auto"}),
            patch("repositories.data_source.REQUIRED_RAW_FILES", (Path("Z:/missing/demo.xlsx"),)),
        ):
            run_pmc_workflow("KQ-Z112", "V01", 100, workflow_id)
            state = get_pmc_workflow_state(workflow_id)

        self.assertEqual(state["workflow_status"], "completed")
        self.assertEqual(state["missing_purchase_parameters"], [])
        self.assertEqual(state["production_decision"]["decision_status"], "procurement_pending")

    def test_raw_mode_keeps_manual_purchase_parameter_behavior(self) -> None:
        mrp_result = {
            "materials": [
                {
                    "material": "RAW-M001",
                    "inventory_status": "known",
                    "shortage": 10,
                }
            ]
        }
        with (
            patch("tools.purchase_tool.resolve_data_source_mode", return_value="raw"),
            patch("tools.purchase_tool.load_demo_purchase_parameters") as demo_loader,
        ):
            result = analyze_real_purchase_for_mrp(mrp_result)

        demo_loader.assert_not_called()
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(len(result["parameter_pending"]), 1)
        self.assertEqual(
            result["parameter_pending"][0]["missing_fields"],
            ["supplier_code", "safety_stock", "lead_time_days"],
        )


if __name__ == "__main__":
    unittest.main()
