"""Controlled confirmations use synthetic workbook fixtures and temporary stores."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.evidence import EvidenceCollector
from agents.response_generator import ResponseGenerator
from agents.business_formatter import format_business_answer
from repositories.agent_context_repository import AgentContextRepository
from repositories.agent_conversation_repository import AgentConversationRepository
from repositories.fact_repository import FactRepository
from repositories.fact_query_repository import FactQueryRepository
from repositories.fact_store import SQLiteFactStore
from repositories.published_bom_confirmation_repository import PublishedBomConfirmationRepository
from scripts.confirm_published_bom_business_facts import execute
from scripts.import_enterprise_boms import audit_directory, stage_audited, publish_staged
from services.fact_query_service import FactQueryService
from services.persistent_agent_service import PersistentAgentService
from services.inventory_import_service import InventoryImportService
from services.production_feasibility_query_service import ProductionFeasibilityQueryService
from services.published_bom_confirmation_service import ConfirmationRequest, PublishedBomConfirmationService
from tests.test_enterprise_bom_catalog import workbook
from tests.test_inventory_fact_import import _create_inventory_workbook


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    workbook(raw / "a.xlsx", "ENTERPRISE-A", "V01", rows=66)
    workbook(raw / "b.xlsx", "ENTERPRISE-B", "V01", rows=91)
    store = SQLiteFactStore(tmp_path / "facts.db")
    facts = FactRepository(store)
    facts.migrate()
    manifest = stage_audited(audit_directory(raw), raw, facts, tmp_path / "report",
                            confirmed_by="synthetic fixture authorization", reason="structure-only release")
    publish_staged(manifest, raw, facts)
    # A had an earlier human-confirmed date; B has none, as in the acceptance contract.
    with store.transaction() as connection:
        store.execute(connection, "UPDATE bom_headers SET effective_from='2025-03-18' WHERE parent_material_code='ENTERPRISE-A'")
    evidence = tmp_path / "human-confirmation.txt"
    evidence.write_text("Explicit synthetic human confirmation of units and separate dates", encoding="utf-8")
    payload = dict(confirmed_by="human_user_request (not employee signature)", reason="explicit human unit/date confirmation",
        evidence_uri="user-confirmation://synthetic", evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        products=[dict(product=code, revision="V01", expected_line_count=count, child_unit="片", effective_from=date,
                       business_publication_date="2026-09-15", analysis_date="2026-09-16",
                       business_snapshot_date="2026-09-11", business_timezone="UTC+08:00")
                  for code, count, date in [("ENTERPRISE-A", 66, "2025-03-18"), ("ENTERPRISE-B", 91, "2026-03-01")]])
    request = ConfirmationRequest.model_validate(payload)
    repository = PublishedBomConfirmationRepository(store)
    service = PublishedBomConfirmationService(repository)
    monkeypatch.setenv("PMC_FACT_DATABASE_URL", f"sqlite:///{store.database_path}")
    monkeypatch.setattr("services.persistent_agent_service.get_llm_configuration_status", lambda: {"status": "warning"})
    monkeypatch.setattr("services.persistent_agent_service.get_llm", lambda: pytest.fail("must not call real LLM"))
    return store, facts, request, repository, service, evidence


def apply(fixture):
    _, _, request, _, service, _ = fixture
    return service.apply(request, service.precheck(request))


def query(fixture, code):
    return FactQueryService(FactQueryRepository(fixture[1])).query_bom(code, "V01")


@pytest.mark.parametrize("code,count", [("ENTERPRISE-A", 66), ("ENTERPRISE-B", 91)])
def test_line_units_confirmed_without_master_or_parent_unit(fixture, code, count):
    apply(fixture)
    result = query(fixture, code)
    assert result["data"]["line_count"] == count
    assert all(row["unit"] == "片" for row in result["data"]["lines"])
    assert all(row["child_item"]["unit"] is None for row in result["data"]["lines"])
    assert result["data"]["parent_item"]["unit"] is None
    assert result["completeness"]["unit"] is True
    assert result["completeness"]["parent_unit"] is False
    assert not any(w.startswith("unit_missing") for w in result["warnings"])
    assert any(w.startswith("parent_unit_missing") for w in result["warnings"])


def test_quantity_identity_source_staging_and_import_audit_unchanged(fixture):
    store, _, request, _, service, _ = fixture
    before = service.precheck(request)
    with store.transaction() as connection:
        old_items = connection.execute("SELECT * FROM items ORDER BY id").fetchall()
        old_staging = connection.execute("SELECT * FROM staged_bom_rows ORDER BY id").fetchall()
        old_batches = connection.execute("SELECT * FROM import_batches ORDER BY id").fetchall()
        old_revisions = connection.execute("SELECT * FROM item_revisions ORDER BY id").fetchall()
    apply(fixture)
    after = service.precheck(request)
    for previous, current in zip(before, after, strict=True):
        for a, b in zip(previous["state"]["lines"], current["state"]["lines"], strict=True):
            assert {k:v for k,v in a.items() if k != "unit"} == {k:v for k,v in b.items() if k != "unit"}
        assert {k:v for k,v in previous["state"]["header"].items() if k != "effective_from"} == {
            k:v for k,v in current["state"]["header"].items() if k != "effective_from"}
    with store.transaction() as connection:
        assert old_items == connection.execute("SELECT * FROM items ORDER BY id").fetchall()
        assert old_staging == connection.execute("SELECT * FROM staged_bom_rows ORDER BY id").fetchall()
        assert old_batches == connection.execute("SELECT * FROM import_batches ORDER BY id").fetchall()
        assert old_revisions == connection.execute("SELECT * FROM item_revisions ORDER BY id").fetchall()


@pytest.mark.parametrize("code,date", [("ENTERPRISE-A", "2025-03-18"), ("ENTERPRISE-B", "2026-03-01")])
def test_effective_date_separate_from_business_publication_and_snapshot(fixture, code, date):
    events = apply(fixture)
    assert query(fixture, code)["data"]["effective_from"] == date
    event = fixture[3].get(next(e["confirmation_id"] for e in events if e["product"] == code))
    assert event["payload"]["business_publication_date"] == "2026-09-15"
    assert event["payload"]["analysis_date"] == "2026-09-16"
    assert event["payload"]["business_snapshot_date"] == "2026-09-11"
    assert event["payload"]["business_timezone"] == "UTC+08:00"
    assert "T" in event["recorded_at"]
    assert event["payload"]["business_publication_date"] not in event["recorded_at"]


def test_confirmation_provenance_returned_without_replacing_original_source(fixture):
    events = apply(fixture)
    result = query(fixture, "ENTERPRISE-A")
    assert result["provenance"]["source_file"] == "a.xlsx"
    audit = result["provenance"]["business_confirmations"][0]
    assert audit["id"] == events[0]["confirmation_id"]
    assert audit["evidence_sha256"] == fixture[2].evidence_sha256
    assert audit["confirmed_fields"]["child_unit"] == "片"
    event = fixture[3].get(audit["id"])
    assert event["before"]["lines"][0]["unit"] is None
    assert event["after"]["lines"][0]["unit"] == "片"


def test_idempotent_retry_never_duplicates_versions_lines_or_imports(fixture):
    manifest = fixture[4].precheck(fixture[2])
    first = fixture[4].apply(fixture[2], manifest)
    second = fixture[4].apply(fixture[2], manifest)
    assert all(e["status"] == "already_applied" for e in second)
    assert [e["confirmation_id"] for e in first] == [e["confirmation_id"] for e in second]
    with fixture[0].transaction() as connection:
        assert connection.execute("SELECT count(*) FROM bom_headers").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM bom_lines").fetchone()[0] == 157
        assert connection.execute("SELECT count(*) FROM import_batches").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM published_bom_confirmations").fetchone()[0] == 2


def test_all_products_transaction_rolls_back_on_second_failure(fixture):
    service, request = fixture[4], fixture[2]
    manifest = service.precheck(request)
    corrupt = copy.deepcopy(manifest)
    corrupt[1]["fingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="changed after precheck"):
        service.apply(request, corrupt)
    assert service.precheck(request) == manifest
    with fixture[0].transaction() as connection:
        assert connection.execute("SELECT count(*) FROM published_bom_confirmations").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("expected_line_count", 65), ("effective_from", "2025-03-19")])
def test_mismatched_count_or_existing_effective_date_rejected(fixture, field, value):
    payload = fixture[2].model_dump()
    payload["products"][0][field] = value
    with pytest.raises(ValueError):
        fixture[4].precheck(ConfirmationRequest.model_validate(payload))


def test_conflicting_line_unit_rejected(fixture):
    with fixture[0].transaction() as connection:
        connection.execute("UPDATE bom_lines SET unit='kg' WHERE id=(SELECT id FROM bom_lines LIMIT 1)")
    with pytest.raises(ValueError, match="conflicting"):
        fixture[4].precheck(fixture[2])


def test_no_inventory_price_or_midnight_snapshot_created(fixture):
    apply(fixture)
    with fixture[0].transaction() as connection:
        for table in ("inventory_snapshots", "inventory_facts", "price_records"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    facts = FactQueryService(FactQueryRepository(fixture[1]))
    result = facts.query_inventory("CHILD-1")
    assert result["status"] == "data_unavailable"
    assert (result.get("data") or {}).get("available_qty") is None
    assert (result.get("data") or {}).get("on_hand_qty") is None


def agent(fixture, *, scoped=True):
    events = apply(fixture)
    context = fixture[3].scoped_context([event["confirmation_id"] for event in events]) if scoped else None
    repository = AgentConversationRepository(fixture[0])
    service = PersistentAgentService(repository)
    service.enable_orchestrator()
    session = repository.create_session(initial_context=context)
    return service, session["session_id"]


@pytest.mark.parametrize("code", ["ENTERPRISE-A", "ENTERPRISE-B"])
def test_scoped_date_not_today_or_bom_start_and_production_not_approved(fixture, code):
    service, session = agent(fixture)
    response = service.query(session, f"生产100台{code}可以吗")
    assert response["status"] == "data_unavailable"
    assert response["structured_data"]["query"]["revision"] == "V01"
    assert response["structured_data"]["query"]["effective_date"] == "2026-09-16"
    assert response["structured_data"]["query"]["as_of"] is None
    assert response["structured_data"]["business_decision"]["status"] == "NOT_APPROVED"
    assert "BOM子料单位已确认：片" in response["answer"]
    assert "成品计量单位尚未确认" in response["answer"]
    assert "库存" in response["answer"]
    assert "BOM的生效日期尚未确认" not in response["answer"]
    assert not any(w.startswith("unit_missing") for w in response["warnings"])


def test_unscoped_session_does_not_inherit_acceptance_date(fixture):
    service, session = agent(fixture, scoped=False)
    response = service.query(session, "生产100台ENTERPRISE-A可以吗")
    assert response["structured_data"]["query"]["effective_date"] is None
    assert "2026-09-16" not in response["answer"]


def test_explicit_user_date_overrides_scoped_confirmation(fixture):
    service, session = agent(fixture)
    service.query(session, "生产100台ENTERPRISE-A可以吗")
    result = service.query(session, "生产100台ENTERPRISE-A，2026-10-20分析")
    assert result["structured_data"]["query"]["effective_date"] == "2026-10-20"


@pytest.mark.parametrize("code,followup,date", [("ENTERPRISE-A", "它的单位是什么？", "2025-03-18"),
                                              ("ENTERPRISE-B", "什么时候生效？", "2026-03-01")])
def test_metadata_followup_uses_current_bom_and_production_context(fixture, code, followup, date):
    service, session = agent(fixture)
    service.query(session, f"{code}的BOM是什么？")
    result = service.query(session, followup)
    assert result["intent"] == "bom"
    assert "片" in result["answer"] and date in result["answer"]
    production = service.query(session, "生产1件可以吗？")
    assert production["intent"] == "production_capacity"
    assert production["structured_data"]["query"]["material_code"] == code
    assert "1台" not in production["answer"]
    assert "数量为1" in production["answer"]


def test_stale_history_not_reused_and_original_history_preserved(fixture):
    repository = AgentConversationRepository(fixture[0])
    service = PersistentAgentService(repository)
    service.enable_orchestrator()
    session = repository.create_session()["session_id"]
    old = service.query(session, "ENTERPRISE-A的BOM是什么")
    assert "物料计量单位尚未确认" in old["answer"]
    apply(fixture)
    refreshed = service.query(session, "为什么？")
    assert refreshed["structured_data"].get("evidence_reused") is not True
    assert "BOM子料计量单位已确认：片" in refreshed["answer"]
    assert repository.history(session)["turns"][0]["response"]["answer"] == old["answer"]


def test_llm_cannot_change_permission_or_inject_inventory(fixture):
    apply(fixture)
    result = dict(status="data_unavailable", query={"material_code": "ENTERPRISE-A", "quantity": 1},
        data={"bom_structure": query(fixture, "ENTERPRISE-A")}, completeness={}, provenance={}, warnings=["权威可用库存数据缺失"])
    evidence = EvidenceCollector().collect("published_bom_context", result["query"], result)
    llm = Mock()
    llm.with_structured_output.return_value.invoke.return_value = {"statement_ids": ["e0"], "answer": "可以生产，库存999件"}
    answer, source = ResponseGenerator(llm_factory=lambda: llm, llm_status=lambda: {"status": "ok"},
                                      formatter=format_business_answer).generate([evidence], ["production_capacity"])
    assert source == "rule_fallback"
    assert "999" not in answer and "不能批准" in answer


def test_default_command_precheck_does_not_update_or_create_session(fixture):
    store, _, request, _, service, _ = fixture
    before = service.precheck(request)
    result = execute(request, store)
    assert result["mode"] == "precheck"
    assert service.precheck(request) == before
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM agent_sessions").fetchone()[0] == 0


def test_apply_command_backups_before_updates_and_binds_only_opted_in_session(fixture):
    store, _, request, _, _, evidence = fixture
    result = execute(request, store, apply=True, evidence_file=evidence, create_acceptance_session=True)
    assert result["backup"]["sha256"]
    assert result["backup_bom_manifest_verified"] is True
    assert hashlib.sha256(Path(result["private_evidence_copy"]["path"]).read_bytes()).hexdigest() == request.evidence_sha256
    assert result["database_before_sha256"] != result["database_after_facts_sha256"]
    assert result["acceptance_session"]["context"]["confirmed_analysis_scope"]
    assert result["inventory_published"] is False


def test_evidence_hash_mismatch_refuses_all_updates(fixture):
    store, _, request, _, service, evidence = fixture
    evidence.write_text("tampered", encoding="utf-8")
    before = service.precheck(request)
    with pytest.raises(ValueError, match="SHA-256"):
        execute(request, store, apply=True, evidence_file=evidence)
    assert before == service.precheck(request)


def test_demo_database_and_context_unchanged(fixture, tmp_path):
    demo = SQLiteFactStore(tmp_path / "separate-demo.db")
    demo.migrate()
    before = hashlib.sha256(Path(demo.database_path).read_bytes()).hexdigest()
    apply(fixture)
    assert before == hashlib.sha256(Path(demo.database_path).read_bytes()).hexdigest()
    assert fixture[3].scoped_context([e["confirmation_id"] for e in apply(fixture)]).get("scenario_id") is None


def test_on_hand_only_inventory_stays_known_but_available_and_units_unknown(fixture, tmp_path):
    source = _create_inventory_workbook(tmp_path / "known-on-hand.xlsx", [["S", "L", "CHILD-1", "B", 12]])
    inventory = InventoryImportService(fixture[1])
    staged = inventory.stage_inventory(source, snapshot_at=datetime(2026, 9, 11, 6, tzinfo=UTC))
    inventory.publish(staged.import_batch_id)
    apply(fixture)
    facts = FactQueryService(FactQueryRepository(fixture[1]))
    result = facts.query_inventory("CHILD-1")
    assert result["data"]["on_hand_qty"] == "12"
    assert result["data"]["available_qty"] is None and result["data"]["reserved_qty"] is None
    assert result["completeness"]["available_qty"] is False
    assert result["data"]["canonical_item"]["unit"] is None


def test_existing_calculation_gate_refuses_units_after_bom_line_confirmation(fixture):
    apply(fixture)
    result = ProductionFeasibilityQueryService(FactQueryService(FactQueryRepository(fixture[1]))).query(
        "ENTERPRISE-A", "V01", requested_quantity=100, effective_date="2026-09-16")
    assert result["status"] == "data_unavailable"
    assert (result.get("data") or {}).get("inventory_sufficient_for_requested") is None
    assert (result.get("data") or {}).get("shortage_qty") is None


def test_conflicting_immutable_evidence_copy_rejected_before_fact_update(fixture):
    store, _, request, _, service, evidence = fixture
    destination = Path(store.database_path).parent / "confirmations" / f"{request.evidence_sha256}.txt"
    destination.parent.mkdir()
    destination.write_text("tampered private evidence", encoding="utf-8")
    before = service.precheck(request)
    with pytest.raises(ValueError, match="modified"):
        execute(request, store, apply=True, evidence_file=evidence)
    assert service.precheck(request) == before


def test_untrusted_or_stale_session_scope_does_not_fill_business_date(fixture):
    apply(fixture)
    repository = AgentContextRepository(FactQueryRepository(fixture[1]))
    with pytest.raises(ValueError, match="scope"):
        repository.confirmed_analysis_context({"confirmed_analysis_scope": {"ENTERPRISE-A": "unknown-event"}}, "ENTERPRISE-A")
    assert repository.confirmed_analysis_context({}, "ENTERPRISE-A") is None
