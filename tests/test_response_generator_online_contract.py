"""Provider-facing JSON contract is explicit; no network calls in unit tests."""

import json

import pytest

from agents.response_generator import GroundedReply
from tests.test_business_answer_quality import bom_result, evidence, generator


def test_json_mode_prompt_includes_exact_schema_and_closing_enum():
    response, runnable = generator({"statement_ids": ["e0"], "closing": "", "layout": "concise"})
    answer, source = response.generate([evidence(bom_result())], ["bom"])
    prompt = runnable.invoke.call_args.args[0][0][1]
    assert json.dumps(GroundedReply.model_json_schema(), ensure_ascii=False) in prompt
    assert '"additionalProperties": false' in prompt
    assert "如需进一步分析，请补充明确的业务条件。" in prompt
    assert source == "llm" and "66" in answer and "V01" in answer


@pytest.mark.parametrize("reply", [
    {"statement_ids": ["e0"], "layout": "concise", "closing": "如需进一步查询，请告知。"},
    {"type": "GroundedReply", "statement_ids": ["e0"], "layout": "concise", "closing": ""},
])
def test_observed_online_invalid_fields_still_refused(reply):
    response, _ = generator(reply)
    answer, source = response.generate([evidence(bom_result())], ["bom"])
    assert source == "rule_fallback"
    assert "66" in answer and "V01" in answer and "2025-03-18" in answer
    assert "如需进一步查询，请告知。" not in answer
