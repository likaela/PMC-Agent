"""v1.4 Chat 多轮上下文、Trace 与方案切换的 API 回归测试。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import app
from workflows.pmc_graph import get_pmc_workflow_state


class ChatSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _start_conversation(self, quantity: int = 100) -> dict[str, object]:
        response = self.client.post("/api/v1/chat", json={"message": f"我要生产{quantity}台KQ-Z112，帮我分析"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_history_records_initial_analysis_turn(self) -> None:
        initial = self._start_conversation()
        workflow_id = initial["conversation_workflow_id"]

        response = self.client.get(f"/api/v1/chat/{workflow_id}/history")

        self.assertEqual(response.status_code, 200)
        history = response.json()["history"]
        self.assertEqual([item["role"] for item in history], ["user", "agent"])
        self.assertEqual({item["turn_type"] for item in history}, {"analysis"})

    def test_explanation_reuses_existing_workflow_context(self) -> None:
        initial = self._start_conversation()
        workflow_id = initial["conversation_workflow_id"]
        before = get_pmc_workflow_state(workflow_id)

        response = self.client.post(
            "/api/v1/chat",
            json={"message": "为什么不能生产？", "workflow_id": workflow_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        after = get_pmc_workflow_state(workflow_id)
        self.assertEqual(payload["turn_type"], "explanation")
        self.assertEqual(payload["workflow_id"], workflow_id)
        self.assertEqual(before["completed_nodes"], after["completed_nodes"])
        self.assertIn("阻塞物料", payload["agent_message"])
        self.assertIn(initial["blocking_materials"][0]["material"], payload["agent_message"])

    def test_reduced_quantity_scenario_keeps_original_workflow_unchanged(self) -> None:
        initial = self._start_conversation()
        workflow_id = initial["conversation_workflow_id"]
        before = get_pmc_workflow_state(workflow_id)

        response = self.client.post(
            "/api/v1/chat",
            json={"message": "减少到50台呢？", "workflow_id": workflow_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        after = get_pmc_workflow_state(workflow_id)
        self.assertEqual(payload["turn_type"], "scenario")
        self.assertEqual(payload["conversation_workflow_id"], workflow_id)
        self.assertEqual(payload["scenario"]["quantity"], 50)
        self.assertNotEqual(payload["workflow_id"], workflow_id)
        self.assertEqual(before["completed_nodes"], after["completed_nodes"])

    def test_history_preserves_multi_turn_order(self) -> None:
        initial = self._start_conversation()
        workflow_id = initial["conversation_workflow_id"]
        for message in ("为什么不能生产？", "减少到50台呢？"):
            response = self.client.post("/api/v1/chat", json={"message": message, "workflow_id": workflow_id})
            self.assertEqual(response.status_code, 200)

        history = self.client.get(f"/api/v1/chat/{workflow_id}/history").json()["history"]
        self.assertEqual(len(history), 6)
        self.assertEqual([item["turn_type"] for item in history], ["analysis", "analysis", "explanation", "explanation", "scenario", "scenario"])

    def test_trace_is_a_public_execution_status_without_internal_state(self) -> None:
        payload = self._start_conversation()
        trace = payload["agent_trace"]
        steps = [item["step"] for item in trace]
        trace_text = str(trace).lower()

        self.assertIn("任务解析", steps)
        self.assertIn("BOM 分析", steps)
        self.assertIn("MRP 齐套分析", steps)
        self.assertNotIn("completed_nodes", trace_text)
        self.assertNotIn("chain of thought", trace_text)
        self.assertNotIn("prompt", trace_text)

    def test_unknown_chat_history_workflow_returns_404(self) -> None:
        response = self.client.get("/api/v1/chat/does-not-exist/history")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("traceback", response.text.lower())


if __name__ == "__main__":
    unittest.main()
