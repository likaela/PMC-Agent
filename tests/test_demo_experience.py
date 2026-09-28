"""v1.5-beta Demo 入口、反馈与当前进程统计测试。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import app


class DemoExperienceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _start_demo_workflow(self) -> dict[str, object]:
        response = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112，帮我分析"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_demo_entry_returns_kq_z112_guided_cases(self) -> None:
        response = self.client.get("/api/v1/demo/cases")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["product"], "KQ-Z112")
        self.assertEqual(payload["bom_version"], "V01")
        self.assertEqual([item["id"] for item in payload["cases"]], [
            "analyze-100", "why-blocked", "reduce-50", "production-impact",
        ])

    def test_demo_example_task_starts_the_existing_pmc_workflow(self) -> None:
        cases = self.client.get("/api/v1/demo/cases").json()["cases"]
        example_message = next(item["message"] for item in cases if item["id"] == "analyze-100")

        response = self.client.post("/api/v1/chat", json={"message": example_message})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parsed_task"], {"product": "KQ-Z112", "bom_version": "V01", "quantity": 100})
        self.assertEqual(payload["workflow_status"], "waiting_for_purchase_parameters")

    def test_feedback_is_accepted_without_exposing_experience_record(self) -> None:
        workflow = self._start_demo_workflow()
        before = self.client.get("/api/v1/demo/statistics").json()["feedback_count"]

        response = self.client.post(
            "/api/v1/demo/feedback",
            json={"workflow_id": workflow["conversation_workflow_id"], "feedback": "阻塞物料说明清晰。"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted"])
        self.assertNotIn("user_input", response.json())
        self.assertEqual(self.client.get("/api/v1/demo/statistics").json()["feedback_count"], before + 1)

    def test_statistics_count_analysis_and_scenario_in_current_process(self) -> None:
        before = self.client.get("/api/v1/demo/statistics").json()
        workflow = self._start_demo_workflow()
        workflow_id = workflow["conversation_workflow_id"]
        scenario = self.client.post(
            "/api/v1/chat",
            json={"message": "如果减少到50台呢？", "workflow_id": workflow_id},
        )

        self.assertEqual(scenario.status_code, 200)
        after = self.client.get("/api/v1/demo/statistics").json()
        self.assertGreaterEqual(after["total_experience_count"], before["total_experience_count"] + 1)
        self.assertGreaterEqual(after["successful_analysis_count"], before["successful_analysis_count"] + 1)
        self.assertEqual(after["scenario_count"], before["scenario_count"] + 1)


if __name__ == "__main__":
    unittest.main()
