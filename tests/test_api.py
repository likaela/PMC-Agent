import json
import os
import unittest

from fastapi.testclient import TestClient

from api.app import app
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from workflows.pmc_graph import get_pmc_workflow_state


class PmcApiTests(unittest.TestCase):
    def setUp(self) -> None:
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
        response = self.client.post(
            f"/api/v1/pmc/{workflow_id}/purchase-parameters",
            json={
                "updates": {
                    "11296476B0101": {
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


if __name__ == "__main__":
    unittest.main()
