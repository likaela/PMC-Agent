"""Synthetic identities only; selection, public HTTP evidence and version guards."""
import copy
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes import agent as route
from repositories.agent_conversation_repository import SessionNotFound
from services.slim_review_service import select_dataset, synthetic_dataset, SlimReviewService
from services.slim_scenario_agent_service import build_slim_scenario_agent
from tests.test_slim_review_scenario import selected
from tests.test_enterprise_book_analysis import book, stock_file
from tests.test_published_bom_business_confirmation import fixture
from tests.test_review_quantity_regression import authorize


def build(book, dataset, tmp_path, version="new-version"):
    d = copy.deepcopy(dataset)
    d["dataset_version"] = version
    path = tmp_path / (version + ".json")
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    service = build_slim_scenario_agent(d["scenario_id"], dataset_path=path, facts=book[0].facts,
        runtime_root=tmp_path / "sessions")
    service.enable_orchestrator()
    return service


def test_positive_stock_below_aggregated_usage_is_excluded(book, tmp_path):
    # Duplicate BOM rows are aggregated before floor; per-row flooring would
    # incorrectly retain this material with stock between one row and the sum.
    original = book[0].facts.query_bom
    bom = original("ENTERPRISE-A", "V01")
    per = Decimal(bom["data"]["lines"][0]["qty_per"])
    bom["data"]["lines"].append(copy.deepcopy(bom["data"]["lines"][0]))
    stock_file(book[4], [["S", "L", book[3][0], "Private name", "LOT", float(per)],
        ["S", "L2", book[3][1], "Private two", "LOT2", 1000]])
    authorize(book, tmp_path)
    with patch.object(book[0].facts, "query_bom", return_value=bom):
        d = select_dataset(book[0], "ENTERPRISE-A", "V01")
    excluded = next(r for r in d["excluded"] if r["material_code"] == book[3][0])
    assert excluded["reason"] == "insufficient_stock_for_one_unit"
    assert excluded["capacity"] == 0 and Decimal(excluded["qty_per"]) == 2 * per
    assert d["retained_material_count"] == 1


@pytest.mark.parametrize("synthetic", [False, True])
def test_new_capacity_all_boundaries_dynamic_not_cached(book, selected, synthetic):
    dataset = synthetic_dataset(selected) if synthetic else selected
    service = SlimReviewService(book[0].facts, dataset)
    maximum = service.analyze("ENTERPRISE-A")["data"]["theoretical_max_quantity"]
    assert maximum == selected["selection_max_quantity"] * (2 if synthetic else 1)
    for n in (1, maximum, maximum + 1, 50, 100):
        d = service.analyze("ENTERPRISE-A", quantity=n)["data"]
        assert d["inventory_sufficient_for_requested"] is (n <= maximum)
    assert service.analyze("ENTERPRISE-A", quantity=0)["status"] == "invalid_query"


def test_public_response_history_and_session_never_export_private_metadata(book, selected, tmp_path, monkeypatch):
    service = build(book, selected, tmp_path)
    monkeypatch.setattr(route, "_persistent_service", lambda _: service)
    before = hashlib.sha256(book[4].read_bytes()).hexdigest()
    with TestClient(app) as client:
        scenario = selected["scenario_id"]
        session = client.post("/api/v1/agent/sessions", json={"scenario_id": scenario}).json()
        sid = session["session_id"]
        assert "dataset_sha256" not in session["context"]
        assert session["context"]["dataset_version"] == "new-version"
        maximum = selected["selection_max_quantity"]
        messages = ["当前是什么场景？", "这个场景有多少项物料？", "最多能生产多少片？",
            "生产1片可以吗？", "生产最大数量可以吗？", "再多生产1片呢？", "哪些物料限制产量？",
            "这些数量来自哪里？", "生产0片。", "那生产1片呢？"]
        responses = []
        with patch.object(service.orchestrator.planner, "llm_factory", side_effect=AssertionError("No private egress")):
            for message in messages:
                r = client.post("/api/v1/agent/query", json={"scenario_id": scenario, "session_id": sid, "message": message})
                assert r.status_code == 200
                responses.append(r.json())
        assert responses[4]["structured_data"]["data"]["requested_quantity"] == maximum
        assert responses[5]["structured_data"]["data"]["requested_quantity"] == maximum + 1
        assert responses[6]["structured_data"]["reused_from_turn_id"]
        assert responses[8]["status"] == "invalid_query"
        assert responses[9]["structured_data"]["data"]["requested_quantity"] == 1
        h = client.get(f"/api/v1/agent/sessions/{sid}", params={"scenario_id": scenario}).json()
        assert len(h["turns"]) == 10
        assert h["turns"][-1]["response"] == responses[-1]
        exported = json.dumps([session, responses, h], ensure_ascii=False)
        assert "MAT-" in exported
        for private in (book[3][0], book[3][1], book[4].name, str(book[4]),
                        hashlib.sha256(book[4].read_bytes()).hexdigest(), "Synthetic A", "content_sha256", "source_uri"):
            assert private not in exported
        assert all(row["available_qty"] is None for row in responses[-1]["structured_data"]["data"]["materials"])
        raw_ref = service.repository.history(sid)["turns"][-1]["fact_references"][0]
        assert raw_ref["result"]["data"]["materials"][0]["material_code"] == book[3][0]
        assert raw_ref["result"]["provenance"] != h["turns"][-1]["fact_references"][0]["provenance"]
    assert hashlib.sha256(book[4].read_bytes()).hexdigest() == before


def test_dataset_version_change_rejects_old_session_without_reinterpreting_history(book, selected, tmp_path):
    old = build(book, selected, tmp_path, "old")
    sid = old.repository.create_session()["session_id"]
    old_response = old.query(sid, "生产1片")
    fresh = build(book, selected, tmp_path, "new")
    with pytest.raises(SessionNotFound, match="different dataset version"):
        fresh.query(sid, "最多能生产多少片")
    assert old.repository.history(sid)["turns"][-1]["response"] == old_response
    assert old_response["structured_data"]["data"]["dataset_version"] == "old"


def test_aliases_stable_for_common_items_across_selection_changes(book, selected, tmp_path):
    stock_file(book[4], [["S", "A", book[3][0], "N", "L", 2000], ["S", "B", book[3][1], "N2", "L2", 2000]])
    authorize(book, tmp_path)
    new = select_dataset(book[0], "ENTERPRISE-A", "V01")
    assert new["retained_material_count"] == 2
    assert selected["material_aliases"] == new["material_aliases"]


def test_maximum_followup_does_not_increment_an_earlier_hundred_quantity(book, selected, tmp_path):
    service = build(book, selected, tmp_path)
    sid = service.repository.create_session()["session_id"]
    service.query(sid, "生产100片")
    service.query(sid, "最多能生产多少片？")
    result = service.query(sid, "再多生产1片呢？")
    assert result["structured_data"]["data"]["requested_quantity"] == selected["selection_max_quantity"] + 1
    assert not result["structured_data"]["data"]["inventory_sufficient_for_requested"]
