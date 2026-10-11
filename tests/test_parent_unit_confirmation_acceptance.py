"""Explicit parent confirmations and current evidence; synthetic facts, no network."""

import copy
from unittest.mock import patch

import pytest

from repositories.agent_conversation_repository import AgentConversationRepository
from services.persistent_agent_service import PersistentAgentService, parse_enterprise_query
from services.published_bom_confirmation_service import ConfirmationRequest
from tools.production_feasibility_query_tool import published_production_capacity_query
from tests.test_published_bom_business_confirmation import fixture, query, apply


def parent_request(fixture):
    data = fixture[2].model_dump()
    for product in data["products"]:
        product["parent_unit"] = "片"
    return ConfirmationRequest.model_validate(data)


def confirm_parents(fixture):
    request = parent_request(fixture)
    return fixture[4].apply(request, fixture[4].precheck(request))


def agent(fixture, *, scoped=False):
    events = confirm_parents(fixture)
    repository = AgentConversationRepository(fixture[0])
    service = PersistentAgentService(repository)
    service.enable_orchestrator()
    context = fixture[3].scoped_context([e["confirmation_id"] for e in events]) if scoped else None
    session = repository.create_session(initial_context=context)["session_id"]
    return service, session


@pytest.mark.parametrize("code,count,date", [
    ("ENTERPRISE-A", 66, "2025-03-18"), ("ENTERPRISE-B", 91, "2026-03-01"),
])
def test_parent_child_units_and_dates_are_current(fixture, code, count, date):
    confirm_parents(fixture)
    result = query(fixture, code)
    assert result["data"]["parent_item"]["unit"] == "片"
    assert result["data"]["effective_from"] == date
    assert len(result["data"]["lines"]) == count
    assert all(row["unit"] == "片" and row["child_item"]["unit"] is None for row in result["data"]["lines"])
    assert result["completeness"]["unit"] and result["completeness"]["parent_unit"]
    assert not any(w.startswith(("unit_missing", "parent_unit_missing", "effective_date_missing")) for w in result["warnings"])
    low_level = fixture[1].get_published_bom(code, "V01")
    assert low_level["header"]["parent_unit"] == "片" and low_level["completeness"]["parent_unit"]


def test_parent_only_followup_audit_does_not_republish_or_rewrite_old_evidence(fixture):
    first = apply(fixture)
    old_events = [fixture[3].get(e["confirmation_id"]) for e in first]
    before = fixture[4].precheck(parent_request(fixture))
    second = confirm_parents(fixture)
    assert all(e["status"] == "applied" for e in second)
    assert [fixture[3].get(e["confirmation_id"]) for e in first] == old_events
    after = fixture[4].precheck(parent_request(fixture))
    for a, b in zip(before, after, strict=True):
        assert a["state"]["lines"] == b["state"]["lines"]
        assert {k:v for k,v in b["state"]["header"].items() if k != "parent_unit"} == a["state"]["header"]
    with fixture[0].transaction() as connection:
        assert connection.execute("SELECT count(*) FROM bom_headers").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM bom_lines").fetchone()[0] == 157
        assert connection.execute("SELECT count(*) FROM import_batches").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM published_bom_confirmations").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM items WHERE material_code NOT IN ('ENTERPRISE-A','ENTERPRISE-B') AND unit IS NOT NULL").fetchone()[0] == 0


def test_parent_update_is_idempotent_and_conflict_is_rejected(fixture):
    request = parent_request(fixture)
    manifest = fixture[4].precheck(request)
    first = fixture[4].apply(request, manifest)
    repeated = fixture[4].apply(request, manifest)
    assert all(e["status"] == "already_applied" for e in repeated)
    assert [e["confirmation_id"] for e in repeated] == [e["confirmation_id"] for e in first]
    conflicting = request.model_dump()
    conflicting["products"][0]["parent_unit"] = "kg"
    with pytest.raises(ValueError, match="parent unit"):
        fixture[4].precheck(ConfirmationRequest.model_validate(conflicting))


@pytest.mark.parametrize("code,quantity", [("ENTERPRISE-A", 100), ("ENTERPRISE-B", 1)])
def test_chinese_date_and_piece_unit_reach_latest_business_evidence(fixture, code, quantity):
    service, session = agent(fixture)
    with patch.object(service.orchestrator.registry, "resolve", wraps=service.orchestrator.registry.resolve) as tools:
        result = service.query(session, f"2026年9月16日生产{quantity}片{code}可以吗？")
    assert result["intent"] == "production_capacity" and result["status"] == "data_unavailable"
    actual = result["structured_data"]["query"]
    assert actual["material_code"] == code and actual["quantity"] == quantity
    assert actual["revision"] == "V01" and actual["effective_date"] == "2026-09-16"
    assert actual["as_of"] is None
    assert result["structured_data"]["business_decision"]["status"] == "NOT_APPROVED"
    assert f"生产{quantity}片" in result["answer"] and f"生产{quantity}台" not in result["answer"]
    assert "成品计量单位已确认：片" in result["answer"]
    assert "物料计量单位尚未确认" not in result["answer"] and "BOM的生效日期尚未确认" not in result["answer"]
    assert "并不代表已经确认库存不足" in result["answer"]
    assert all(d in result["answer"] for d in ("2026-09-15", "2026-09-16", "2026-09-11", "UTC+08:00", "尚未确认具体时刻"))
    assert not any(w.startswith(("unit_missing", "parent_unit_missing", "effective_date_missing")) for w in result["warnings"])
    tools.assert_not_called()  # Missing authoritative snapshot must stop calculation.
    history = service.repository.history(session)
    references = history["turns"][0]["fact_references"]
    structure = next(ref["result"]["data"]["bom_structure"] for ref in references
                     if "bom_structure" in (ref["result"].get("data") or {}))
    assert structure["data"]["parent_item"]["unit"] == "片"


def test_current_metadata_followups_and_why_reuse(fixture):
    service, session = agent(fixture)
    for question in ("查询ENTERPRISE-B的BOM", "什么时候生效？", "成品单位是什么？"):
        response = service.query(session, question)
        assert response["intent"] == "bom"
        assert response["structured_data"]["data"]["parent_item"]["unit"] == "片"
        assert "2026-03-01" in response["answer"]
    first = service.query(session, "2026年9月16日生产1片可以吗？")
    assert first["structured_data"]["query"]["material_code"] == "ENTERPRISE-B"
    with patch.object(service.orchestrator.registry, "resolve", side_effect=AssertionError("No recompute")):
        why = service.query(session, "为什么不能批准？")
    assert why["structured_data"]["reused_result"]["data"]["bom_structure"]["data"]["parent_item"]["unit"] == "片"
    assert "生产1片" in why["answer"]


def test_colloquial_piece_needs_confirmation_not_conversion(fixture):
    service, session = agent(fixture)
    with patch.object(service.orchestrator.registry, "resolve", side_effect=AssertionError("No conversion")):
        response = service.query(session, "2026年9月16日生产一件ENTERPRISE-B可以吗？")
    assert response["status"] == "needs_input"
    assert "件" in response["answer"] and "按1片分析" in response["answer"]
    assert "未确认等价关系" in response["answer"]


def test_no_global_analysis_date_and_explicit_date_overrides_session(fixture):
    service, session = agent(fixture)
    result = service.query(session, "生产1片ENTERPRISE-B可以吗？")
    assert result["structured_data"]["query"]["effective_date"] is None
    assert "本次生产分析日期为 2026-09-16" not in result["answer"]
    assert not any("请补充BOM生效日期" in warning for warning in result["warnings"])
    scoped, scoped_session = agent(fixture, scoped=True)
    result = scoped.query(scoped_session, "2026年10月20日生产1片ENTERPRISE-B可以吗？")
    assert result["structured_data"]["query"]["effective_date"] == "2026-10-20"
    assert "本次生产分析日期为 2026-10-20" in result["answer"]


def test_snapshot_stays_date_only_and_child_inventory_unknown(fixture):
    events = confirm_parents(fixture)
    for e in events:
        fields = fixture[3].get(e["confirmation_id"])["payload"]
        assert fields["business_snapshot_date"] == "2026-09-11"
        assert fields["business_timezone"] == "UTC+08:00"
        assert "snapshot_at" not in fields
    with fixture[0].transaction() as connection:
        for table in ("inventory_facts", "inventory_snapshots", "price_records"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    result = published_production_capacity_query.invoke(dict(product="ENTERPRISE-B", bom_version="V01",
        effective_date="2026-09-16", requested_quantity=1, requested_unit="片"))
    assert result["status"] == "data_unavailable"
    assert not any("产品计量单位" in w for w in result["warnings"])
    assert (result.get("data") or {}).get("inventory_sufficient_for_requested") is None
    assert (result.get("data") or {}).get("theoretical_max_quantity") is None


def test_old_parent_warning_is_not_reused_but_history_is_kept(fixture):
    apply(fixture)
    repository = AgentConversationRepository(fixture[0])
    service = PersistentAgentService(repository)
    service.enable_orchestrator()
    session = repository.create_session()["session_id"]
    old = service.query(session, "查询ENTERPRISE-B的BOM")
    assert "成品计量单位尚未确认" in old["answer"]
    original = copy.deepcopy(repository.history(session)["turns"])
    confirm_parents(fixture)
    new = service.query(session, "为什么？")
    assert "成品计量单位尚未确认" not in new["answer"]
    assert "成品计量单位已确认：片" in new["answer"]
    assert repository.history(session)["turns"][:1] == original


@pytest.mark.parametrize("question,quantity", [
    ("生产1片ENTERPRISE-B", 1), ("ENTERPRISE-B生产一片", 1),
    ("2026年9月16日生产100片ENTERPRISE-B", 100),
])
def test_piece_quantity_and_calendar_are_not_material_codes(question, quantity):
    task, _ = parse_enterprise_query(question, allow_llm=False)
    assert task.material_code == "ENTERPRISE-B" and task.quantity == quantity
