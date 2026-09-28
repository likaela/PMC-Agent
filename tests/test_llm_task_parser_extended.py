"""v1.6-alpha.1 中文任务理解与主动澄清测试；DeepSeek 均为 mock。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from services.llm_task_parser_service import parse_production_task_with_llm


class _StructuredStub:
    def __init__(self, response: object) -> None:
        self.response = response

    def invoke(self, _messages: object) -> object:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _LlmStub:
    def __init__(self, response: object) -> None:
        self.response = response

    def with_structured_output(self, _schema: object, *, method: str) -> _StructuredStub:
        if method != "json_mode":
            raise AssertionError("任务解析必须使用受控 JSON 模式")
        return _StructuredStub(self.response)


class ExtendedLlmTaskParserTests(unittest.TestCase):
    def test_chinese_number_one_hundred_and_two_hundred(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("offline"))):
            one_hundred = parse_production_task_with_llm("生产KQ-Z112一百台")
            two_hundred = parse_production_task_with_llm("帮我安排两百个KQ-Z112")

        self.assertEqual(one_hundred.quantity, 100)
        self.assertEqual(two_hundred.quantity, 200)
        self.assertEqual(one_hundred.parser_source, "rule_fallback")

    def test_numeric_quantity_with_each_supported_unit(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("offline"))):
            hundred_items = parse_production_task_with_llm("帮我安排100个KQ-Z112")
            two_hundred_units = parse_production_task_with_llm("下个月生产200台KQ-Z112")

        self.assertTrue(hundred_items.is_complete)
        self.assertEqual(hundred_items.quantity, 100)
        self.assertEqual(two_hundred_units.quantity, 200)

    def test_product_missing_returns_clarification_without_workflow(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("offline"))):
            response = TestClient(app).post("/api/v1/chat", json={"message": "我要生产100台"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_type"], "clarification")
        self.assertEqual(payload["task_intent"]["quantity"], 100)
        self.assertEqual(payload["missing_fields"], ["产品型号"])
        self.assertIn("请补充产品型号", payload["agent_message"])
        self.assertNotIn("workflow_id", payload)

    def test_quantity_missing_returns_clarification_without_workflow(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("offline"))):
            response = TestClient(app).post("/api/v1/chat", json={"message": "我要生产KQ-Z112"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_intent"]["product"], "KQ-Z112")
        self.assertEqual(payload["missing_fields"], ["生产数量"])
        self.assertIn("请补充生产数量", payload["agent_message"])
        self.assertNotIn("workflow_id", payload)

    def test_deepseek_exception_automatically_uses_rule_fallback(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub(RuntimeError("timeout"))):
            task = parse_production_task_with_llm("KQ-Z112做50台可以吗")

        self.assertEqual(task.parser_source, "rule_fallback")
        self.assertEqual(task.quantity, 50)

    def test_invalid_json_automatically_uses_rule_fallback(self) -> None:
        with patch("services.llm_task_parser_service.get_llm", return_value=_LlmStub("not-json")):
            task = parse_production_task_with_llm("我要生产100台KQ-Z112")

        self.assertEqual(task.parser_source, "rule_fallback")
        self.assertEqual(task.product, "KQ-Z112")
        self.assertEqual(task.quantity, 100)


if __name__ == "__main__":
    unittest.main()
