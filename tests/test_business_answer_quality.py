"""Business prose stays grounded; LLM is mocked, real tools use temporary facts."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agents.business_answer import business_decision, human_warning
from agents.business_formatter import format_business_answer
from agents.evidence import EvidenceCollector
from agents.response_generator import ResponseGenerator
from repositories.agent_conversation_repository import AgentConversationRepository
from services.persistent_agent_service import PersistentAgentService
from services.demo_scenario_agent_service import build_demo_scenario_agent
from tests.test_kq_z112_enterprise_import import enterprise_files, repository
from tests.test_incomplete_bom_publication import publish_structure, fact_query


@pytest.fixture
def business(repository, enterprise_files, monkeypatch):
    publish_structure(repository, enterprise_files)
    monkeypatch.setenv("PMC_FACT_DATABASE_URL", f"sqlite:///{Path(repository.store.database_path).as_posix()}")
    service = PersistentAgentService(AgentConversationRepository(repository.store))
    service.enable_orchestrator()
    session = service.repository.create_session()["session_id"]
    with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"}), \
         patch("services.persistent_agent_service.get_llm", side_effect=AssertionError("No external API")):
        yield service, session, repository


def query(business, message):
    return business[0].query(business[1], message)


def evidence(result):
    return EvidenceCollector().collect("published_bom_query", result["query"], result)


def test_bom_summary_and_complete_table(business):
    result = query(business, "查询KQ-Z112的BOM")
    assert result["status"] == "ok"
    assert all(text in result["answer"] for text in ("KQ-Z112", "V01", "66", "2025-03-18", "物料表", "单位"))
    assert "价格" not in result["answer"]
    assert not any(w.startswith("price_missing") for w in result["warnings"])
    assert result["structured_data"]["completeness"]["price"] is False
    assert len(result["structured_data"]["data"]["lines"]) == 66
    assert all(line["unit"] is None and line["price"] is None for line in result["structured_data"]["data"]["lines"])
    assert "M-001" not in result["answer"] and "M-066" not in result["answer"]
    assert "缺料" not in result["answer"]  # Structural completeness is not a stock verdict.


@pytest.mark.parametrize("internal", ["unit_missing", "price_missing", "import_batch", "published_bom_query", "content_sha256"])
def test_no_internal_prose(business, internal):
    result = query(business, "查询KQ-Z112的BOM")
    assert internal not in result["answer"]
    assert result["provenance"]["content_sha256"] not in result["answer"]
    assert result["provenance"]["import_batch_id"] not in result["answer"]
    assert any("unit_missing" in warning for warning in result["warnings"])


@pytest.mark.parametrize("key,label", [
    ("unit_missing", "计量单位"), ("price_missing", "价格"),
    ("effective_date_missing", "生效日期"), ("available_qty_missing", "权威可用库存"),
    ("inventory_unknown", "库存事实"), ("data_unavailable", "信息不足"),
])
def test_warning_translation(key, label):
    assert key not in human_warning(key) and label in human_warning(key)


def test_unknown_date_is_not_fabricated():
    result = bom_result()
    result["data"]["effective_from"] = None
    result["completeness"]["effective_from"] = False
    text = format_business_answer("bom", result)
    assert "生效日期尚未确认" in text and "2025-03-18" not in text


def test_production_not_approved_is_not_confirmed_shortage(business):
    result = query(business, "生产100台KQ-Z112可以吗")
    text = result["answer"]
    assert "当前不能批准生产100台 KQ-Z112" in text
    assert all(word in text for word in ("V01", "66", "计量单位", "权威可用库存", "并不代表已经确认库存不足", "证据不足"))
    assert result["structured_data"]["data"] is None
    assert result["structured_data"]["business_decision"]["reason"] == "NOT_APPROVED_DUE_TO_INSUFFICIENT_EVIDENCE"
    assert result["provenance"]["content_sha256"]
    assert "缺口 0" not in text and "缺口25" not in text


def test_why_reuses_incomplete_published_evidence(business):
    first = query(business, "生产100台KQ-Z112可以吗")
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("No recompute")), \
         patch.object(business[0].orchestrator.context_resolver.repository, "structure_evidence", side_effect=AssertionError("No reread")):
        reason = query(business, "为什么不能生产？")
    assert "证据不足" in reason["answer"]
    assert reason["structured_data"]["completed_steps"] == []
    assert reason["provenance"] == first["provenance"]


@pytest.mark.parametrize("first", ["KQ-Z112怎么样？", "KQ-Z112有多少种物料？"])
def test_natural_product_context_is_retained(business, first):
    initial = query(business, first)
    assert initial["intent"] == "bom" and "66" in initial["answer"]
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("Evidence reuse")):
        followup = query(business, "主要是什么？")
    assert followup["structured_data"]["reused_result"]["data"]["line_count"] == 66
    next_task = query(business, "生产100台呢？")
    assert next_task["intent"] == "production_capacity"
    assert next_task["structured_data"]["query"]["material_code"] == "KQ-Z112"
    assert next_task["structured_data"]["query"]["quantity"] == 100
    assert "当前不能批准" in next_task["answer"]


def test_source_question_uses_existing_evidence_without_raw_audit_dump(business):
    first = query(business, "查询KQ-Z112的BOM")
    with patch("langchain_core.tools.BaseTool.invoke", side_effect=AssertionError("Evidence reuse")):
        result = query(business, "这个结论从哪里来的？")
    assert "来自企业已发布的 KQ-Z112 V01 BOM" in result["answer"]
    assert {key: value for key, value in first["provenance"].items() if key != "context_resolution"} == result["provenance"]
    assert result["provenance"]["content_sha256"] not in result["answer"]


def bom_result():
    return dict(status="ok", query={"parent_material_code": "KQ-Z112", "revision": "V01"},
        data={"parent_item": {"material_code": "KQ-Z112", "unit": None}, "revision": "V01",
              "line_count": 66, "effective_from": "2025-03-18",
              "lines": [{"child_item": {"name": "电容"}, "qty_per": "2", "unit": None, "price": None}]},
        completeness={"unit": False, "parent_unit": False, "price": False, "effective_from": True},
        provenance={"content_sha256": "a" * 64, "source_file": "bom.xls"}, warnings=["unit_missing", "price_missing"])


def generator(reply=None, *, exception=None):
    runnable = Mock()
    runnable.invoke.side_effect = exception
    runnable.invoke.return_value = reply
    llm = Mock()
    llm.with_structured_output.return_value = runnable
    return ResponseGenerator(llm_factory=lambda: llm, llm_status=lambda: {"status": "ok"},
        formatter=format_business_answer), runnable


@pytest.mark.parametrize("invalid", [
    {"statement_ids": ["e0"], "answer": "V02共99项，可以生产100台"},
    {"statement_ids": ["e0"], "quantity": 999},
    {"statement_ids": ["e66"]}, {"statement_ids": ["e0", "e0"]}, "not JSON", None,
])
def test_llm_cannot_change_facts_or_omit_required_warning(invalid):
    result = bom_result()
    before = copy.deepcopy(result)
    gen, _ = generator(invalid)
    text, source = gen.generate([evidence(result)], ["bom"])
    assert source == "rule_fallback"
    assert "66" in text and "V01" in text and "计量单位" in text
    assert "价格" not in text  # Structural queries do not require a cost warning.
    assert result["completeness"]["price"] is False
    assert "V02" not in text and "999" not in text and result == before


def test_llm_receives_validated_evidence_not_only_raw_template():
    result = bom_result()
    gen, call = generator({"statement_ids": ["e0"], "layout": "briefing"})
    text, source = gen.generate([evidence(result)], ["bom"])
    payload = json.loads(call.invoke.call_args.args[0][1][1])
    assert payload["evidence"][0]["output"] == result
    assert payload["business_decisions"][0]["status"] == "INFORMATIONAL"
    assert source == "llm" and "电容" in text and "66" in text


def test_timeout_business_fallback_preserves_structured_facts():
    gen, _ = generator(exception=TimeoutError("private traceback secret"))
    text, source = gen.generate([evidence(bom_result())], ["bom"])
    assert source == "rule_fallback" and "66" in text
    assert "secret" not in text and "traceback" not in text


def test_demo_true_shortage_remains_distinct_and_isolated(tmp_path):
    service = build_demo_scenario_agent(runtime_root=tmp_path / "demo")
    service.enable_orchestrator()
    session = service.repository.create_session()["session_id"]
    with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"}), \
         patch("repositories.fact_store.create_fact_store", side_effect=AssertionError("No enterprise")):
        result = service.query(session, "生产100台DEMO-PMC-01")
        enough = service.query(session, "减少到50台呢")
    assert result["structured_data"]["data"]["inventory_sufficient_for_requested"] is False
    assert "不足" in result["answer"] and "证据不足" not in result["answer"]
    assert business_decision("production_capacity", dict(status="ok", data=result["structured_data"]["data"]))["reason"] == "CANNOT_PRODUCE_DUE_TO_SHORTAGE"
    assert enough["structured_data"]["data"]["inventory_sufficient_for_requested"] is True
    assert result["provenance"]["synthetic"] is True


def test_inventory_null_and_on_hand_are_not_reinterpreted_as_available():
    result = dict(status="ok", query={"material_code": "MAT-001"}, data={"on_hand_qty": "44", "available_qty": None, "reserved_qty": None})
    text = format_business_answer("inventory", result)
    assert "在库数量为 44" in text and "可用数量为 未知" in text
    assert "可用数量为 44" not in text and "数量为 0" not in text


def test_material_categories_only_use_explicit_published_names():
    result = bom_result()
    result["data"]["lines"][0]["child_item"]["name"] = "名称未提供"
    text = format_business_answer("bom", result)
    assert "电容" not in text and "芯片" not in text
    assert "主要包括" not in text


def test_llm_cannot_rewrite_same_known_numbers_between_fields():
    # A numeric allowlist alone would accept this permutation of valid tokens.
    gen, _ = generator({"statement_ids": ["e0"], "answer": "V66，共1项物料，生效日期2025-18-03"})
    text, source = gen.generate([evidence(bom_result())], ["bom"])
    assert source == "rule_fallback"
    assert "V01" in text and "66 项" in text and "2025-03-18" in text
    assert "V66" not in text
