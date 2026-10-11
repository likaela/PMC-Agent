"""A private real-BOM simulation is not published enterprise or public Demo."""
from unittest.mock import patch
import hashlib

import pytest

from services.review_scenario_agent_service import build_review_scenario_agent, SCENARIO_ID
from repositories.agent_conversation_repository import SessionNotFound
from tests.test_enterprise_book_analysis import book
from tests.test_published_bom_business_confirmation import fixture
from tests.test_review_quantity_regression import authorize


def test_simulation_50_positive_100_negative_keeps_raw_and_facts(book,tmp_path):
    authorize(book,tmp_path)
    source=book[4]; before=hashlib.sha256(source.read_bytes()).hexdigest()
    service=build_review_scenario_agent(facts=book[0].facts,observations=book[0].observations,
        product="ENTERPRISE-A",revision="V01",runtime_root=tmp_path/"review")
    service.enable_orchestrator()
    session=service.repository.create_session()["session_id"]
    with patch.object(service.orchestrator.planner,"llm_factory",side_effect=AssertionError("No private egress")):
        positive=service.query(session,"生产50片可以吗")
        negative=service.query(session,"生产100片呢")
        invalid=service.query(session,"生产0个")
        one=service.query(session,"生产1个")
    assert positive["scenario_id"] == SCENARIO_ID
    assert positive["structured_data"]["data"]["inventory_sufficient_for_requested"] is True
    assert "可以满足生产50片" in positive["answer"] and "合成补充库存" in positive["answer"]
    assert negative["structured_data"]["data"]["inventory_sufficient_for_requested"] is False
    assert invalid["status"] == "invalid_query"
    assert one["structured_data"]["data"]["requested_quantity"] == 1
    assert len(one["structured_data"]["data"]["materials"]) == 66
    assert positive["provenance"]["inventory"]
    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
    assert not book[0].analyze("ENTERPRISE-A",quantity=50)["data"]["inventory_sufficient_for_requested"]
    with service.repository.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM inventory_facts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM bom_headers").fetchone()[0] == 0
    with pytest.raises(SessionNotFound):
        book[1].repository.get_session(session)
    restored=build_review_scenario_agent(facts=book[0].facts,observations=book[0].observations,
        product="ENTERPRISE-A",revision="V01",runtime_root=tmp_path/"review")
    assert restored.repository.history(session)["turns"][-1]["response"] == one
    assert service.book_service.analyze("ENTERPRISE-B",quantity=50)["status"] == "data_unavailable"


def test_review_is_blocked_in_public_trial(book,tmp_path,monkeypatch):
    monkeypatch.setenv("PMC_TRIAL_MODE","1")
    with pytest.raises(PermissionError):
        build_review_scenario_agent(facts=book[0].facts,observations=book[0].observations,
            product="ENTERPRISE-A",revision="V01",runtime_root=tmp_path/"review")
