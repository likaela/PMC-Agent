import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from workflows.pmc_graph import get_pmc_workflow_state


class PmcApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.purchase_mode_patcher = patch(
            "tools.purchase_tool.resolve_data_source_mode",
            return_value="raw",
        )
        self.purchase_mode_patcher.start()
        self.addCleanup(self.purchase_mode_patcher.stop)
        self.client = TestClient(app)

    def analyze_kq(self) -> dict[str, object]:
        response = self.client.post(
            "/api/v1/pmc/analyze",
            json={"product": "KQ-Z112", "bom_version": "V01", "quantity": 1},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_swagger_docs_are_available(self) -> None:
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Swagger UI", response.text)

    def test_analyze_returns_workflow_id_and_public_contract(self) -> None:
        payload = self.analyze_kq()
        self.assertTrue(payload["workflow_id"])
        self.assertEqual(payload["workflow_status"], "waiting_for_purchase_parameters")
        self.assertEqual(payload["decision_status"], "blocked")
        self.assertFalse(payload["can_start_production"])
        self.assertNotIn("completed_nodes", payload)

    def test_analyze_invalid_input_returns_422(self) -> None:
        response = self.client.post(
            "/api/v1/pmc/analyze",
            json={"product": "KQ-Z112", "bom_version": "V01", "quantity": 0},
        )
        self.assertEqual(response.status_code, 422)

    def test_kq_analyze_waits_for_eight_purchase_parameter_items(self) -> None:
        payload = self.analyze_kq()
        self.assertEqual(len(payload["blocking_materials"]), 8)
        self.assertEqual(len(payload["missing_purchase_parameters"]), 8)
        self.assertEqual(payload["report"]["purchase_recommendations"], [])

    def test_get_workflow_returns_current_public_state(self) -> None:
        analyzed = self.analyze_kq()
        response = self.client.get(f"/api/v1/pmc/{analyzed['workflow_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workflow_id"], analyzed["workflow_id"])
        self.assertEqual(response.json()["report"], analyzed["report"])

    def test_purchase_parameter_resume_does_not_repeat_bom_or_mrp(self) -> None:
        analyzed = self.analyze_kq()
        workflow_id = analyzed["workflow_id"]
        initial_state = get_pmc_workflow_state(workflow_id)
        material = analyzed["missing_purchase_parameters"][0]["material"]
        response = self.client.post(
            f"/api/v1/pmc/{workflow_id}/purchase-parameters",
            json={
                "updates": {
                    material: {
                        "supplier_code": "SUP001",
                        "safety_stock": 10,
                        "lead_time_days": 8,
                    }
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        resumed_state = get_pmc_workflow_state(workflow_id)
        self.assertEqual(payload["workflow_status"], "waiting_for_purchase_parameters")
        self.assertEqual(len(payload["missing_purchase_parameters"]), 7)
        self.assertEqual(resumed_state["completed_nodes"].count("bom_analysis"), 1)
        self.assertEqual(resumed_state["completed_nodes"].count("mrp_analysis"), 1)
        self.assertGreater(
            resumed_state["completed_nodes"].count("purchase_analysis"),
            initial_state["completed_nodes"].count("purchase_analysis"),
        )

    def test_unknown_workflow_returns_404(self) -> None:
        response = self.client.get("/api/v1/pmc/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("traceback", response.text.lower())

    def test_api_result_matches_deterministic_report(self) -> None:
        payload = self.analyze_kq()
        deterministic = build_kq_z112_report()
        self.assertEqual(payload["report"]["production_decision"], deterministic["production_decision"])
        self.assertEqual(payload["report"]["shortage_list"], deterministic["shortage_list"])

    def test_api_does_not_expose_sensitive_environment_values(self) -> None:
        secret = "test-secret-that-must-not-be-returned"
        previous = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = secret
        try:
            payload = self.analyze_kq()
            self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))
        finally:
            if previous is None:
                del os.environ["DEEPSEEK_API_KEY"]
            else:
                os.environ["DEEPSEEK_API_KEY"] = previous

    def test_chat_parses_chinese_task_and_reuses_pmc_workflow(self) -> None:
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "我要生产100台KQ-Z112，帮我看看能不能开工"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["parsed_task"],
            {"product": "KQ-Z112", "bom_version": "V01", "quantity": 100},
        )
        direct_response = self.client.post(
            "/api/v1/pmc/analyze",
            json={"product": "KQ-Z112", "bom_version": "V01", "quantity": 100},
        )
        self.assertEqual(direct_response.status_code, 200)
        direct_payload = direct_response.json()
        self.assertEqual(payload["workflow_status"], "waiting_for_purchase_parameters")
        self.assertEqual(payload["decision_status"], direct_payload["decision_status"])
        self.assertEqual(payload["blocking_materials"], direct_payload["blocking_materials"])
        self.assertEqual(payload["report"], direct_payload["report"])
        self.assertNotIn("completed_nodes", payload)

    def test_chat_returns_user_facing_clarification_when_task_parameters_are_missing(self) -> None:
        response = self.client.post("/api/v1/chat", json={"message": "帮我看看能不能开工"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_type"], "clarification")
        self.assertEqual(payload["missing_fields"], ["产品型号", "生产数量"])
        self.assertNotIn("workflow_id", payload)

    def test_public_execution_steps_show_tools_without_internal_state(self) -> None:
        payload = self.analyze_kq()
        steps = payload["execution_steps"]
        self.assertEqual(steps[0]["tool"], "输入校验")
        self.assertIn("real_bom_check", [step["tool"] for step in steps])
        self.assertEqual(steps[-1]["status"], "waiting")
        self.assertNotIn("completed_nodes", json.dumps(steps, ensure_ascii=False))
        self.assertNotIn("prompt", json.dumps(steps, ensure_ascii=False).lower())

    def test_chat_turns_missing_purchase_parameters_into_follow_up_questions(self) -> None:
        response = self.client.post("/api/v1/chat", json={"message": "我要生产1台KQ-Z112"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["follow_up_questions"]), 8)
        first_material = payload["missing_purchase_parameters"][0]["material"]
        self.assertIn(first_material, payload["follow_up_questions"][0])
        self.assertIn("supplier_code", payload["follow_up_questions"][0])
        self.assertIn("采购参数", payload["agent_message"])


if __name__ == "__main__":
    unittest.main()
