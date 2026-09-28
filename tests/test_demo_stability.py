"""v1.8 Demo 稳定性：公开错误、重开分析与恢复接口的回归测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app


class DemoStabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_repeated_demo_analysis_creates_a_new_workflow_when_not_reusing_session(self) -> None:
        first = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112，帮我分析"})
        second = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112，帮我分析"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["workflow_id"], second.json()["workflow_id"])
        self.assertNotEqual(first.json()["conversation_workflow_id"], second.json()["conversation_workflow_id"])

    def test_valid_workflow_and_chat_history_are_available_for_frontend_session_restore(self) -> None:
        created = self.client.post("/api/v1/chat", json={"message": "我要生产100台KQ-Z112，帮我分析"}).json()

        workflow = self.client.get(f"/api/v1/pmc/{created['workflow_id']}")
        history = self.client.get(f"/api/v1/chat/{created['conversation_workflow_id']}/history")

        self.assertEqual(workflow.status_code, 200)
        self.assertEqual(history.status_code, 200)
        self.assertIn("report", workflow.json())
        self.assertGreaterEqual(len(history.json()["history"]), 2)

    def test_invalid_workflow_uses_sanitized_session_expired_error(self) -> None:
        response = self.client.get("/api/v1/pmc/workflow-not-found")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload, {
            "code": "SESSION_EXPIRED",
            "user_message": "当前演示会话已失效，请重新开始分析。",
        })
        self.assertNotIn("workflow", payload["user_message"].lower())
        self.assertNotIn("traceback", response.text.lower())
        self.assertNotIn("detail", payload)

    def test_internal_workflow_exception_does_not_reach_public_error_body(self) -> None:
        with patch("api.routes.pmc.run_pmc_workflow", side_effect=RuntimeError("secret internal stack detail")):
            response = self.client.post(
                "/api/v1/pmc/analyze",
                json={"product": "KQ-Z112", "bom_version": "V01", "quantity": 1},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {
            "code": "ANALYSIS_UNAVAILABLE",
            "user_message": "分析服务暂时异常，请稍后重试。",
        })
        self.assertNotIn("secret internal", response.text)

    def test_error_workflow_hides_internal_report_and_returns_public_error(self) -> None:
        from api.routes.pmc import _workflow_response

        response = _workflow_response(
            "workflow-error",
            {
                "workflow_status": "error",
                "errors": ["internal tool exception"],
                "report": {"errors": ["internal tool exception"]},
            },
        )

        self.assertEqual(response.report, {})
        self.assertEqual(response.public_error.code, "ANALYSIS_UNAVAILABLE")
        self.assertNotIn("internal tool exception", response.model_dump_json())


if __name__ == "__main__":
    unittest.main()
