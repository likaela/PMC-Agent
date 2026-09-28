"""v1.6 受控 LLM 任务解析测试：所有模型调用均为本地 mock。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from api.schemas.llm_task import ProductionTaskIntent
from services.llm_task_parser_service import parse_production_task_with_llm


class _StructuredLlmStub:
    def __init__(self, response: object) -> None:
        self.response = response
        self.messages: object | None = None

    def invoke(self, messages: object) -> object:
        self.messages = messages
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _LlmStub:
    def __init__(self, response: object) -> None:
        self.response = response
        self.schema: object | None = None
        self.method: str | None = None

    def with_structured_output(self, schema: object, *, method: str) -> _StructuredLlmStub:
        self.schema = schema
        self.method = method
        return _StructuredLlmStub(self.response)


class LlmTaskParserTests(unittest.TestCase):
    def test_valid_structured_json_returns_llm_intent(self) -> None:
        llm = _LlmStub(
            {
                "intent": "analysis",
                "product": "kq-z112",
                "bom_version": "v1",
                "quantity": 200,
                "missing_fields": [],
            }
        )

        with patch("services.llm_task_parser_service.get_llm", return_value=llm):
            task = parse_production_task_with_llm("我要生产200台KQ-Z112")

        self.assertEqual(task.parser_source, "llm")
        self.assertEqual(task.model_dump(), {
            "intent": "analysis",
            "product": "KQ-Z112",
            "bom_version": "V01",
            "quantity": 200,
            "missing_fields": [],
            "parser_source": "llm",
        })
        self.assertEqual(llm.method, "json_mode")

    def test_invalid_structured_response_falls_back_to_rule_parser(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub("not-a-json-object")):
            task = parse_production_task_with_llm("我要生产200台KQ-Z112")

        self.assertEqual(task.parser_source, "rule_fallback")
        self.assertEqual(task.quantity, 200)

    def test_llm_api_failure_falls_back_to_rule_parser(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            task = parse_production_task_with_llm("我要生产200台KQ-Z112")

        self.assertEqual(task.parser_source, "rule_fallback")
        self.assertEqual(task.product, "KQ-Z112")

    def test_missing_llm_fields_return_clarification_intent(self) -> None:
        with patch(
            "services.llm_task_parser_service.get_llm",
            return_value=_LlmStub({"intent": "analysis", "product": "KQ-Z112", "missing_fields": ["生产数量"]}),
        ):
            task = parse_production_task_with_llm("我要生产200台KQ-Z112")

        self.assertEqual(task.parser_source, "llm")
        self.assertEqual(task.product, "KQ-Z112")
        self.assertIsNone(task.quantity)
        self.assertEqual(task.missing_fields, ["生产数量"])

    def test_rule_fallback_supports_chinese_quantity_and_common_word_orders(self) -> None:
        examples = {
            "我要生产100台KQ-Z112": 100,
            "生产KQ-Z112一百台": 100,
            "帮我安排200个KQ-Z112": 200,
            "下个月生产100台KQ-Z112": 100,
            "KQ-Z112做50台可以吗": 50,
        }
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            for message, quantity in examples.items():
                with self.subTest(message=message):
                    task = parse_production_task_with_llm(message)
                    self.assertTrue(task.is_complete)
                    self.assertEqual(task.product, "KQ-Z112")
                    self.assertEqual(task.quantity, quantity)
                    self.assertEqual(task.parser_source, "rule_fallback")

    def test_product_only_task_returns_quantity_clarification(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            task = parse_production_task_with_llm("我要生产KQ-Z112")

        self.assertFalse(task.is_complete)
        self.assertEqual(task.product, "KQ-Z112")
        self.assertEqual(task.missing_fields, ["生产数量"])

    def test_quantity_only_task_returns_product_clarification(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            task = parse_production_task_with_llm("我要生产100台")

        self.assertFalse(task.is_complete)
        self.assertEqual(task.quantity, 100)
        self.assertEqual(task.missing_fields, ["产品型号"])

    def test_unparseable_message_returns_safe_clarification_intent(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            task = parse_production_task_with_llm("帮我看看能不能开工")

        self.assertFalse(task.is_complete)
        self.assertEqual(task.missing_fields, ["产品型号", "生产数量"])

    def test_chat_route_uses_validated_llm_task_without_business_calculation(self) -> None:
        expected = ProductionTaskIntent(
            intent="analysis",
            product="KQ-Z112",
            bom_version="V01",
            quantity=200,
            parser_source="llm",
        )

        with patch("api.routes.chat.parse_production_task_with_llm", return_value=expected):
            from fastapi.testclient import TestClient
            from api.app import app

            response = TestClient(app).post("/api/v1/chat", json={"message": "我要生产200台KQ-Z112"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parsed_task"], {"product": "KQ-Z112", "bom_version": "V01", "quantity": 200})
        self.assertEqual(payload["task_intent"]["parser_source"], "llm")
        self.assertEqual(payload["task_intent"]["quantity"], 200)

    def test_chat_route_returns_user_facing_clarification_without_workflow(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            from fastapi.testclient import TestClient
            from api.app import app

            response = TestClient(app).post("/api/v1/chat", json={"message": "我要生产KQ-Z112"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_type"], "clarification")
        self.assertEqual(payload["missing_fields"], ["生产数量"])
        self.assertIn("已识别产品 KQ-Z112", payload["agent_message"])
        self.assertNotIn("workflow_id", payload)


if __name__ == "__main__":
    unittest.main()
