"""Current product source is independent; original facts/history remain immutable."""
import copy
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.test_enterprise_book_analysis import book
from tests.test_published_bom_business_confirmation import fixture
from tests.test_slim_review_scenario import selected
from tests.test_review_quantity_regression import authorize
from tests.test_authorized_review import SECRET, ask
from repositories.current_business_repository import CurrentBusinessRepository
from repositories.agent_conversation_repository import SessionNotFound
from scripts.prepare_current_business_bom import prepare
from services.current_business_service import build_current_business_agent
from services.reviewer_agent_service import ReviewBinding


@pytest.fixture
def current(book, selected, tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.prepare_current_business_bom.ROOT", tmp_path)
    monkeypatch.setattr("services.reviewer_agent_service.ENTERPRISE_PRODUCTS", ("ENTERPRISE-A", "ENTERPRISE-B"))
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(selected), encoding="utf-8")
    manifest = prepare(path, tmp_path / "current", archive_paths=[book[4]])
    source = CurrentBusinessRepository(manifest)
    binding = ReviewBinding(facts_path=book[0].facts.repository.store.database_path, inventory_path=book[4],
        units_path=tmp_path / "units.json", quantity_path=authorize(book, tmp_path),
        runtime_root=tmp_path / "review", business_manifest_path=manifest)
    from api.review_app import create_review_app
    with TestClient(create_review_app(binding, SECRET, {"a":["ENTERPRISE-A", "ENTERPRISE-B", "DEMO-PMC-01"], "b":["DEMO-PMC-01"]})) as client:
        client.headers.update({"X-PMC-Proxy-Key":SECRET, "X-PMC-User":"a"})
        yield source, binding, client, manifest


def session(client):
    return client.post("/api/v1/agent/sessions", json={"product_code":"ENTERPRISE-A"}).json()["session_id"]


def test_only_current_scope_and_distinct_revision_no_legacy_read(current, book):
    source, binding, client, _ = current
    entry = client.get("/api/v1/review/catalog").json()["products"][0]
    assert entry["default_mode"] == "current" and len(entry["modes"]) == 1
    assert entry["revision"] != "V01" and entry["line_count"] == len(source.aliases)
    assert client.post("/api/v1/agent/sessions", json={"product_code":"ENTERPRISE-A", "analysis_mode":"full"}).status_code == 422
    assert client.get("/api/v1/review/products/ENTERPRISE-A/materials?analysis_mode=full").status_code == 422
    assert len(book[0].facts.query_bom("ENTERPRISE-A", "V01")["data"]["lines"]) == 66
    with patch("services.reviewer_agent_service.ScopedFacts.get_published_bom", side_effect=AssertionError("No historic BOM")):
        result = ask(client, session(client), "查询ENTERPRISE-A的BOM").json()
    assert result["status"] == "ok" and len(result["structured_data"]["data"]["materials"]) == len(source.aliases)


@pytest.mark.parametrize("message", ["查询ENTERPRISE-A", "查询ENTERPRISE-A的BOM", "有哪些物料", "查看全部物料", "查看库存", "这些数量来自哪里"])
def test_queries_bind_current_sources(current, message):
    source, binding, client, _ = current
    result = ask(client, session(client), message).json()
    assert result["status"] == "ok", result
    data = result["structured_data"]["data"]
    assert data.get("total_material_count", data.get("line_count")) == len(source.aliases)
    assert "66" not in result["answer"] and result["review_mode"] == "current"
    assert result["dataset_version"] == source.version
    assert result["scenario_id"] is None


def test_dynamic_capacity_boundary_and_unknown_not_filled(current):
    source, binding, client, _ = current
    service = binding.services[source.product]
    maximum = min(int(sum(Decimal(r["recorded_stock_qty"]) for r in source.observations["records"][l["child_item"]["material_code"]]) // Decimal(l["qty_per"])) for l in source.bom["data"]["lines"])
    sid = session(client)
    for n in (1, maximum, maximum + 1, 50, 100):
        result = ask(client, sid, f"生产{n}片").json()
        data = result["structured_data"]["data"]
        assert data["requested_quantity"] == n and data["theoretical_max_quantity"] == maximum
        assert data["inventory_sufficient_for_requested"] == (n <= maximum)
        assert all(r["available_qty"] is None and r["reserved_qty"] is None for r in data["materials"])
        assert "最大" not in result["answer"]
    context = copy.deepcopy(service.repository.get_session(sid)["context"])
    with patch.object(type(service.book_queries.tools["enterprise_book_demand_analysis"]), "invoke", side_effect=AssertionError("Zero must not call tool")):
        assert ask(client, sid, "生产0片").json()["status"] == "invalid_query"
    assert service.repository.get_session(sid)["context"] == context
    assert ask(client, sid, "生产1片").json()["structured_data"]["data"]["requested_quantity"] == 1

def test_capacity_query_does_not_erase_quantity_explanation(current):
    _, binding, client, _ = current
    sid = session(client)
    first = ask(client, sid, "生产50片").json()
    ask(client, sid, "最多可以生产多少片")
    with patch.object(binding.services["ENTERPRISE-A"].book_service.observations, "load", side_effect=AssertionError("Evidence only")):
        why = ask(client, sid, "哪些物料不足").json()
    assert why["structured_data"]["data"]["requested_quantity"] == 50
    assert why["structured_data"]["reused_from_turn_id"] == first["turn_id"]


def test_reuse_restart_history_exact_version_and_owner(current):
    source, binding, client, manifest = current
    sid = session(client)
    first = ask(client, sid, "生产2片").json()
    service = binding.services[source.product]
    with patch.object(service.book_service.observations, "load", side_effect=AssertionError("Do not recalculate")):
        why = ask(client, sid, "为什么不能生产").json()
    assert why["structured_data"]["reused_from_turn_id"] == first["turn_id"]
    assert why["structured_data"]["data"] == first["structured_data"]["data"]
    restored = build_current_business_agent(manifest, runtime_root=binding.runtime / "current-business")
    from services.reviewer_agent_service import public_review_payload
    assert public_review_payload(restored.public_session(restored.repository.history(sid)))["turns"][0]["response"]["structured_data"]["data"] == first["structured_data"]["data"]
    restored.repository.source.manifest_hash = "different"
    with pytest.raises(SessionNotFound):
        restored.repository.history(sid)
    client.headers["X-PMC-User"] = "b"
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 404


def test_hash_mismatch_rejected_and_original_archive_preserved(current):
    source, _, _, manifest = current
    archive = json.loads((manifest.parent / "private_audit.json").read_text(encoding="utf-8"))
    assert source.observations["quantity_confirmation"]["quantity_field"] == "recorded_stock_qty"
    rows = [row for values in source.observations["records"].values() for row in values]
    assert [row["provenance"]["row_number"] for row in rows] == list(range(1, len(rows)+1))
    assert len(archive["inventory_lineage"]) == len(rows)
    for row in archive["archives"]:
        assert hashlib.sha256((manifest.parent / "private_archive" / row["archive_path"]).read_bytes()).hexdigest() == row["sha256"]
    inventory = manifest.parent / "inventory.json"
    inventory.write_bytes(inventory.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        source.verify_sources()
    with pytest.raises(ValueError, match="integrity"):
        CurrentBusinessRepository(manifest)


def test_archived_request_and_foreign_material_never_returns_full(current):
    source, _, client, _ = current
    sid = session(client)
    result = ask(client, sid, "查询原始66项历史BOM").json()
    assert result["status"] == "data_unavailable" and result["structured_data"]["data"] is None
    assert ask(client, sid, "查询MAT-999库存").status_code == 404
    assert ask(client, sid, "生产1片", scenario_id="kq_z112_review_slim").status_code == 422
    assert ask(client, sid, "查询ENTERPRISE-A V01的BOM").json()["status"] == "data_unavailable"


def test_trial_cannot_load_working_source(current, monkeypatch):
    _, _, _, manifest = current
    monkeypatch.setenv("PMC_TRIAL_MODE", "1")
    with pytest.raises(PermissionError):
        CurrentBusinessRepository(manifest)

def test_greeting_does_not_calculate_or_export_business_evidence(current):
    source, binding, client, _ = current
    sid = session(client)
    tool = binding.services[source.product].book_queries.tools["enterprise_book_demand_analysis"]
    with patch.object(type(tool), "invoke", side_effect=AssertionError("Greeting must not query stock")):
        result = ask(client, sid, "你好").json()
    assert result["status"] == "ok"
    assert result["structured_data"]["completed_steps"] == []
    assert binding.services[source.product].repository.history(sid)["turns"][0]["fact_references"] == []

def test_inventory_failure_retains_bom_demand_without_old_source_fallback(current):
    source, binding, client, _ = current
    sid = session(client)
    with patch.object(binding.services[source.product].book_service.observations, "load", side_effect=OSError("Synthetic source unavailable")):
        result = ask(client, sid, "生产2片").json()
    assert result["status"] == "data_unavailable"
    data = result["structured_data"]["data"]
    assert len(data["materials"]) == len(source.aliases)
    assert data["requested_quantity"] == 2 and data["stock_read_failed"]
    for row in data["materials"]:
        assert Decimal(row["required_qty"]) == Decimal(row["qty_per"]) * 2
        assert row["recorded_stock_qty"] is None and row["shortage_qty"] is None
    assert data["theoretical_max_quantity"] is None and data["inventory_sufficient_for_requested"] is None
