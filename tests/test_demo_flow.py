"""v1.8-beta 四阶段比赛 Demo 流程回归。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import app
from workflows.pmc_graph import get_pmc_workflow_state


class CompleteDemoFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_complete_demo_flow_uses_existing_chat_and_scenario_endpoints(self) -> None:
        initial = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112"})
        self.assertEqual(initial.status_code, 200)
        initial_payload = initial.json()
        original_workflow_id = initial_payload["workflow_id"]
        original_state = get_pmc_workflow_state(original_workflow_id)

        explanation = self.client.post(
            "/api/v1/chat",
            json={"message": "为什么不能生产？", "workflow_id": original_workflow_id},
        )
        self.assertEqual(explanation.status_code, 200)
        self.assertEqual(explanation.json()["turn_type"], "explanation")

        scenario = self.client.post(
            "/api/v1/chat",
            json={"message": "减少到50台呢？", "workflow_id": original_workflow_id},
        )
        self.assertEqual(scenario.status_code, 200)
        scenario_payload = scenario.json()
        scenario_workflow_id = scenario_payload["workflow_id"]
        self.assertEqual(scenario_payload["turn_type"], "scenario")
        self.assertEqual(scenario_payload["parsed_task"]["quantity"], 50)
        self.assertEqual(get_pmc_workflow_state(original_workflow_id)["completed_nodes"], original_state["completed_nodes"])

        impact = self.client.post(
            "/api/v1/chat",
            json={"message": "哪些物料影响最大？", "workflow_id": scenario_workflow_id},
        )
        self.assertEqual(impact.status_code, 200)
        impact_payload = impact.json()
        self.assertEqual(impact_payload["turn_type"], "impact")
        self.assertEqual(impact_payload["parsed_task"]["quantity"], 50)
        self.assertIn("阻塞项", impact_payload["agent_message"])

    def test_supported_key_material_variants_use_existing_impact_logic(self) -> None:
        initial = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112"}).json()
        for message in ("哪些物料影响生产？", "哪些物料最关键？", "哪些材料影响最大？"):
            with self.subTest(message=message):
                response = self.client.post(
                    "/api/v1/chat",
                    json={"message": message, "workflow_id": initial["workflow_id"]},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["turn_type"], "impact")

    def test_free_form_new_analysis_remains_independent_of_demo_conversation(self) -> None:
        first = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112"}).json()
        second = self.client.post("/api/v1/chat", json={"message": "我要生产200台KQ-Z112"}).json()

        self.assertNotEqual(first["workflow_id"], second["workflow_id"])
        self.assertEqual(second["parsed_task"]["quantity"], 200)


if __name__ == "__main__":
    unittest.main()
