"""v1.8.1 比赛发布加固回归。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import config
from api.app import _allowed_origins, app
from repositories.data_source import get_data_source_status, resolve_data_source_mode
from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from services.llm_task_parser_service import parse_production_task_with_llm


class ReleaseHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_synthetic_demo_data_reproduces_kq_workflow_without_raw_excel(self) -> None:
        with patch.dict(os.environ, {"PMC_DATA_SOURCE": "demo"}):
            report = build_kq_z112_report()

        self.assertEqual(report["bom_material_count"], 66)
        self.assertEqual(report["mrp_material_count"], 44)
        self.assertEqual(report["inventory_data_integrity"]["excluded_inventory_data_error_count"], 22)
        self.assertEqual(len(report["production_decision"]["blocking_materials"]), 8)

    def test_auto_data_source_falls_back_to_demo_when_raw_files_are_unavailable(self) -> None:
        with (
            patch.dict(os.environ, {"PMC_DATA_SOURCE": "auto"}),
            patch("repositories.data_source.REQUIRED_RAW_FILES", (Path("Z:/missing/demo.xlsx"),)),
        ):
            self.assertEqual(resolve_data_source_mode(), "demo")
            self.assertEqual(get_data_source_status()["status"], "ok")

    def test_localhost_and_loopback_origins_are_allowed_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            origins = _allowed_origins()
        self.assertIn("http://localhost:5173", origins)
        self.assertIn("http://127.0.0.1:5173", origins)
        self.assertNotIn("*", origins)

    def test_cors_preflight_accepts_both_local_frontend_hosts(self) -> None:
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            with self.subTest(origin=origin):
                response = self.client.options(
                    "/api/v1/chat",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_llm_has_bounded_timeout_and_retry(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "not-a-real-key",
                    "DEEPSEEK_BASE_URL": "https://example.invalid",
                    "LLM_TIMEOUT_SECONDS": "4",
                    "LLM_MAX_RETRIES": "1",
                },
                clear=True,
            ),
            patch("config.ChatOpenAI") as chat_openai,
        ):
            config.get_llm()
        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["request_timeout"], 4.0)
        self.assertEqual(kwargs["max_retries"], 1)

    def test_llm_timeout_uses_rule_fallback(self) -> None:
        llm = MagicMock()
        llm.with_structured_output.side_effect = TimeoutError("network timeout")
        with patch("services.llm_task_parser_service.get_llm", return_value=llm):
            task = parse_production_task_with_llm("我要生产100台KQ-Z112")
        self.assertEqual(task.parser_source, "rule_fallback")
        self.assertEqual(task.quantity, 100)

    def test_detailed_health_check_is_ready_and_does_not_expose_secrets(self) -> None:
        secret = "health-check-secret"
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": secret, "PMC_DATA_SOURCE": "demo"}):
            response = self.client.get("/health?details=true")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"]["data"]["mode"], "demo")
        self.assertEqual(payload["checks"]["workflow"]["status"], "ok")
        self.assertNotIn(secret, response.text)
        self.assertNotIn("API_KEY", response.text)

    def test_default_health_contract_remains_unchanged(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
