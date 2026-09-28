"""v1.6-beta 结果解释层测试：LLM 一律以本地 mock 替代。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.explanation_service import explain_pmc_result


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


def _blocked_facts() -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    report = {
        "production_decision": {
            "decision_status": "blocked",
            "can_start_production": False,
            "decision_reasons": ["存在确定缺料"],
            "recommended_actions": ["补充采购参数"],
        },
        "purchase_parameter_missing_items": [{"material": "M-HIGH"}],
        "data_limitations_and_assumptions": ["库存仅使用主库存表"],
    }
    decision = report["production_decision"]
    materials = [
        {
            "priority": 1,
            "material": "M-HIGH",
            "shortage": 10,
            "purchase_status": "需要补充采购参数",
            "risk_level": None,
            "missing_fields": ["supplier_code", "safety_stock", "lead_time_days"],
        },
        {
            "priority": 2,
            "material": "M-LOW",
            "shortage": 2,
            "purchase_status": "需要补充采购参数",
            "risk_level": None,
            "missing_fields": ["supplier_code"],
        },
    ]
    return report, decision, materials


class ExplanationServiceTests(unittest.TestCase):
    def test_blocked_explanation_uses_structured_llm_text_only(self) -> None:
        report, decision, materials = _blocked_facts()
        llm = _LlmStub({"answer": "结构化报告显示 M-HIGH 缺料，因此当前不能开工。"})

        with patch("services.explanation_service.get_llm", return_value=llm):
            result = explain_pmc_result(
                question="为什么不能生产？",
                topic="blocked",
                production_report=report,
                production_decision=decision,
                missing_materials=materials,
            )

        self.assertEqual(result.source, "llm")
        self.assertEqual(result.topic, "blocked")
        self.assertEqual(result.answer, "结构化报告显示 M-HIGH 缺料，因此当前不能开工。")
        self.assertEqual(llm.method, "json_mode")

    def test_ready_explanation_falls_back_to_existing_decision(self) -> None:
        report = {"production_decision": {"decision_status": "ready", "can_start_production": True}}
        with patch("services.explanation_service.get_llm", side_effect=RuntimeError("offline")):
            result = explain_pmc_result(
                question="可以生产吗？",
                topic="ready",
                production_report=report,
                production_decision=report["production_decision"],
                missing_materials=[],
            )

        self.assertEqual(result.source, "template_fallback")
        self.assertIn("可开工", result.answer)
        self.assertIn("阻塞物料", result.answer)

    def test_impact_explanation_preserves_existing_material_priority(self) -> None:
        report, decision, materials = _blocked_facts()
        with patch("services.explanation_service.get_llm", side_effect=RuntimeError("offline")):
            result = explain_pmc_result(
                question="哪些物料影响生产？",
                topic="impact",
                production_report=report,
                production_decision=decision,
                missing_materials=materials,
            )

        self.assertEqual(result.source, "template_fallback")
        self.assertLess(result.answer.index("P1 M-HIGH"), result.answer.index("P2 M-LOW"))
        self.assertIn("缺料 10", result.answer)

    def test_llm_failure_returns_blocked_template_without_invented_fields(self) -> None:
        report, decision, materials = _blocked_facts()
        with patch("services.explanation_service.get_llm", return_value=_LlmStub(RuntimeError("network unavailable"))):
            result = explain_pmc_result(
                question="为什么不能生产？",
                topic="blocked",
                production_report=report,
                production_decision=decision,
                missing_materials=materials,
            )

        self.assertEqual(result.source, "template_fallback")
        self.assertIn("M-HIGH", result.answer)
        self.assertIn("待补采购参数物料", result.answer)
        self.assertNotIn("供应商为", result.answer)


if __name__ == "__main__":
    unittest.main()
