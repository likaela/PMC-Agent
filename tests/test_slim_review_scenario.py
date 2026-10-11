"""Synthetic fixtures only. Same Agent/Tools, filtered facts never published."""
import copy
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.test_enterprise_book_analysis import book, stock_file
from tests.test_published_bom_business_confirmation import fixture
from tests.test_review_quantity_regression import authorize
from services.slim_review_service import select_dataset, synthetic_dataset, SlimReviewService, REAL_SLIM, SYNTHETIC_SLIM
from services.slim_scenario_agent_service import build_slim_scenario_agent
from repositories.agent_conversation_repository import SessionNotFound


@pytest.fixture
def selected(book, tmp_path):
    authorize(book, tmp_path)
    d = select_dataset(book[0], "ENTERPRISE-A", "V01")
    d.update(dataset_version="fixture-version", display_product_code="EXAMPLE-REVIEW-SLIM")
    return d


def test_selection_uses_aggregated_capacity_and_audits_exclusion(book, selected):
    assert selected["retained_material_count"] == 1
    assert len(selected["excluded"]) == 65
    assert selected["zero_stock_retained"] == []
    assert set(r["reason"] for r in selected["excluded"]) == {"no_main_inventory_record", "zero_stock_quantity"}
    assert selected["bom"]["data"]["lines"][0]["qty_per"] == book[0].facts.query_bom("ENTERPRISE-A", "V01")["data"]["lines"][0]["qty_per"]
    assert selected["observations"]["records"][book[3][0]][0]["provenance"]["row_number"] == 2
    assert len(book[0].analyze("ENTERPRISE-A", quantity=1)["data"]["materials"]) == 66


def test_real_subset_recomputed_capacity_preserves_full_enterprise_zero_rows(book, selected):
    service = SlimReviewService(book[0].facts, selected)
    result = service.analyze("ENTERPRISE-A", quantity=1)
    data = result["data"]
    assert data["theoretical_max_quantity"] == selected["selection_max_quantity"] >= 1
    assert data["inventory_sufficient_for_requested"]
    full = book[0].analyze("ENTERPRISE-A", quantity=1)["data"]
    assert any(r["recorded_stock_qty"] == "0" for r in full["materials"])
    assert all(r["available_qty"] is None for r in data["materials"])


@pytest.mark.parametrize("n", [0, 1, 50, 100, 51])
def test_synthetic_boundaries_use_same_calculation_service(book, selected, n):
    d = synthetic_dataset(selected, 50)
    result = SlimReviewService(book[0].facts, d).analyze("ENTERPRISE-A", quantity=n)
    if n == 0:
        assert result["status"] == "invalid_query" and result["data"] is None
        return
    data = result["data"]
    assert data["theoretical_max_quantity"] == 50
    assert data["inventory_sufficient_for_requested"] is (n <= 50)
    for row in data["materials"]:
        assert Decimal(row["required_qty"]) == Decimal(row["qty_per"]) * n
        assert Decimal(row["shortage_qty"]) == max(Decimal(row["required_qty"]) - Decimal(row["recorded_stock_qty"]), 0)
    assert data["formal_production_approved"] is False
    assert result["provenance"]["filtered_dataset"]["synthetic"]


@pytest.mark.parametrize("bad,reason", [(None,"invalid_stock_quantity"),(-1,"invalid_stock_quantity"),("bad","invalid_stock_quantity"),("duplicate","unresolved_duplicate_observations")])
def test_bad_record_excluded_not_summed(book, tmp_path, bad, reason):
    code = book[3][0]
    rows = [["S","A",code,"N","L",5 if bad=="duplicate" else bad]]
    if bad == "duplicate":
        rows += copy.deepcopy(rows)
    rows += [["S","B",book[3][1],"Valid","L2",1000]]
    stock_file(book[4], rows)
    authorize(book, tmp_path)
    d = select_dataset(book[0], "ENTERPRISE-A", "V01")
    assert d["retained_material_count"] == 1
    assert next(r for r in d["excluded"] if r["material_code"] == code)["reason"] == reason


def test_empty_subset_rejects_capacity(book, tmp_path):
    stock_file(book[4], [])
    authorize(book, tmp_path)
    with pytest.raises(ValueError, match="No verified"):
        select_dataset(book[0], "ENTERPRISE-A", "V01")


@pytest.mark.parametrize("synthetic", [False, True])
def test_agent_queries_boundaries_history_isolation_no_private_egress(book, selected, tmp_path, synthetic):
    d = synthetic_dataset(selected, 50) if synthetic else selected
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    service = build_slim_scenario_agent(d["scenario_id"], dataset_path=path, facts=book[0].facts, runtime_root=tmp_path/"runtime")
    service.enable_orchestrator()
    sid = service.repository.create_session()["session_id"]
    raw_hash = hashlib.sha256(book[4].read_bytes()).hexdigest()
    with patch.object(service.orchestrator.planner,"llm_factory",side_effect=AssertionError("Private egress forbidden")):
        for q,n in [("现在有哪些物料参与计算？",None),("生产1片可以吗",1),("生产50片",50),("生产100片",100)]:
            r=service.query(sid,q)
            assert r["status"] == "ok" and r["structured_data"]["data"]["requested_quantity"] == n
            assert len(r["structured_data"]["data"]["materials"]) == 1
        with patch.object(type(service.book_queries.tools["enterprise_book_demand_analysis"]), "invoke", side_effect=AssertionError("0 must not invoke Tool")):
            invalid=service.query(sid,"生产零个")
        assert invalid["status"] == "invalid_query"
        assert service.repository.get_session(sid)["context"]["slim_analysis"]["quantity"] == 100
        r=service.query(sid,"最多可以生产多少片？")
        m=r["structured_data"]["data"]["theoretical_max_quantity"]
        assert m == (50 if synthetic else selected["selection_max_quantity"])
        r=service.query(sid,"生产最大数量可以吗？")
        assert r["structured_data"]["data"]["inventory_sufficient_for_requested"]
        r=service.query(sid,"再多生产1片呢？")
        assert r["structured_data"]["data"]["requested_quantity"] == m + 1
        assert r["structured_data"]["data"]["book_shortages"]
        with patch.object(type(service.book_queries.tools["enterprise_book_demand_analysis"]), "invoke", side_effect=AssertionError("Reuse Evidence")):
            for q in ["为什么不能生产？","哪些物料限制产量？","这些库存数量来自哪里？"]:
                r=service.query(sid,q)
                assert r["structured_data"]["reused_from_turn_id"]
    assert raw_hash == hashlib.sha256(book[4].read_bytes()).hexdigest()
    assert service.repository.history(sid)["turns"][-1]["response"] == r
    restored=build_slim_scenario_agent(d["scenario_id"],dataset_path=path,facts=book[0].facts,runtime_root=tmp_path/"runtime")
    assert restored.repository.history(sid)["turns"][-1]["response"] == r
    with pytest.raises(SessionNotFound):
        book[1].repository.get_session(sid)
    with service.repository.store.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM bom_lines").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM inventory_facts").fetchone()[0] == 0
    assert service.book_service.analyze("ENTERPRISE-B",quantity=1)["status"] == "data_unavailable"
