"""Enterprise context resolution uses real temporary SQLite published facts, never LLM guesses."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from api.schemas.agent import UnifiedAgentResponse
from agents.context_resolver import ContextResolver
from agents.orchestrator import AgentOrchestrator
from agents.tool_registry import ToolRegistry
from repositories.agent_conversation_repository import AgentConversationRepository
from services.persistent_agent_service import PersistentAgentService
from services.demo_scenario_agent_service import build_demo_scenario_agent
from tests import test_published_purchase_planning as fixtures
from tests.test_inventory_fact_import import _seed_item


class EnterpriseContextResolverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublishedPurchasePlanningTests(methodName="test_moq_is_used_when_positive_requirement_is_smaller")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.items["KQ-Z112"] = _seed_item(self.fixture.facts, "KQ-Z112")
        self.repository = AgentConversationRepository(self.fixture.store)
        self.service = PersistentAgentService(self.repository)
        self.service.enable_orchestrator()
        self.session_id = self.repository.create_session()["session_id"]
        environment = patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{self.fixture.database.as_posix()}"})
        environment.start()
        self.addCleanup(environment.stop)
        llm = patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"})
        llm.start()
        self.addCleanup(llm.stop)
        guard = patch("services.persistent_agent_service.get_llm", side_effect=AssertionError("Tests must not call an external LLM"))
        guard.start()
        self.addCleanup(guard.stop)

    def bom(self, revision="V01", start="2026-09-01", end=None, *, published=True):
        self.fixture._bom([("MAT-001", "1")], parent="KQ-Z112")
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection,
                "UPDATE bom_headers SET version=?, effective_from=?, effective_to=? WHERE parent_material_code='KQ-Z112' AND version='V1'",
                (revision, start, end))
            if not published:
                self.fixture.store.execute(connection,
                    "UPDATE import_batches SET status='staged' WHERE id=(SELECT import_batch_id FROM bom_headers WHERE parent_material_code='KQ-Z112' AND version=?)",
                    (revision,))

    def stock(self, at="2026-10-01T00:00:00+00:00"):
        self.fixture._inventory({"MAT-001": "150"}, at=at)

    def query(self, message):
        response = self.service.query(self.session_id, message)
        UnifiedAgentResponse.model_validate(response)
        return response

    def resolutions(self, response):
        return {entry["field"]: entry for entry in response["structured_data"]["context_evidence"]}

    def test_unique_effective_bom_completes_natural_production_request(self):
        self.bom()
        self.stock()
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(response["structured_data"]["query"]["revision"], "V01")
        self.assertEqual(response["structured_data"]["query"]["effective_date"], "2026-10-01")
        evidence = self.resolutions(response)
        self.assertEqual(evidence["revision"]["source"], "published_bom_context")
        self.assertEqual(evidence["revision"]["value"], "V01")
        self.assertEqual(evidence["effective_date"]["value"], "2026-10-01")
        self.assertEqual(evidence["as_of"]["source"], "published_inventory_context")
        self.assertIn("V01", response["answer"])
        self.assertEqual(response["provenance"]["context_resolution"]["evaluated_on"], "2026-10-01")

    def test_user_revision_v02_is_kept_even_when_versions_overlap(self):
        self.bom()
        self.bom("V02", start="2026-09-15")
        self.stock()
        response = self.query("生产100台KQ-Z112，使用V02")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V02")
        self.assertNotIn("revision", self.resolutions(response))

    def test_multiple_effective_versions_require_clarification_and_no_tool(self):
        self.bom()
        self.bom("V02", start="2026-09-15")
        self.stock()
        with patch.object(self.service.orchestrator.registry, "resolve", wraps=self.service.orchestrator.registry.resolve) as tool:
            response = self.query("生产100台KQ-Z112可以吗")
        tool.assert_not_called()
        self.assertEqual(response["status"], "needs_input")
        self.assertEqual(response["answer"], "当前存在多个有效BOM版本，请确认。")
        self.assertIsNone(response["structured_data"]["query"]["revision"])
        self.assertEqual({row["revision"] for row in response["structured_data"]["context_resolution"]["candidates"]}, {"V01", "V02"})

    def test_no_published_bom_refuses_without_computation(self):
        self.stock()
        with patch.object(self.service.orchestrator.registry, "resolve", wraps=self.service.orchestrator.registry.resolve) as tool:
            response = self.query("生产100台KQ-Z112可以吗")
        tool.assert_not_called()
        self.assertEqual(response["status"], "data_unavailable")
        self.assertIn("没有该产品的已发布BOM", response["answer"])

    def test_unpublished_bom_and_snapshot_are_not_used(self):
        self.bom()
        self.bom("V02", published=False)
        self.stock()
        self.stock("2026-12-01T00:00:00+00:00")
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection,
                "UPDATE import_batches SET status='staged' WHERE id=(SELECT import_batch_id FROM inventory_snapshots WHERE snapshot_at='2026-12-01T00:00:00+00:00')")
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "ok")
        evidence = self.resolutions(response)
        self.assertEqual(evidence["revision"]["value"], "V01")
        self.assertEqual(evidence["effective_date"]["value"], "2026-10-01")

    def test_future_and_expired_versions_not_chosen(self):
        self.bom(start="2026-12-01")
        self.stock()
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "data_unavailable")
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection,
                "UPDATE bom_headers SET effective_from='2026-01-01', effective_to='2026-09-30' WHERE parent_material_code='KQ-Z112'")
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "data_unavailable")

    def test_effective_intervals_choose_unique_not_latest_label(self):
        self.bom("V99", start="2026-01-01", end="2026-09-30")
        self.bom("V02", start="2026-10-01")
        self.stock()
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V02")

    def test_explicit_user_effective_date_is_preserved(self):
        self.bom("V01", start="2026-01-01", end="2026-09-30")
        self.bom("V02", start="2026-10-01")
        self.stock()
        response = self.query("生产100台KQ-Z112 生效日期2026-09-20")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V01")
        self.assertEqual(response["structured_data"]["query"]["effective_date"], "2026-09-20")
        self.assertNotIn("effective_date", self.resolutions(response))
        self.assertEqual(response["provenance"]["context_resolution"]["date_basis"]["source"], "user_business_date")

    def test_unlabeled_explicit_user_date_not_replaced_with_fact_date(self):
        self.bom("V01", start="2026-01-01", end="2026-09-30")
        self.bom("V02", start="2026-10-01")
        self.stock()
        response = self.query("2026-09-20生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["effective_date"], "2026-09-20")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V01")

    def test_ambiguous_or_invalid_unlabeled_dates_require_clarification(self):
        self.bom()
        self.stock()
        for message in ("2026-10-02或2026-10-03生产100台KQ-Z112", "2026-02-30生产100台KQ-Z112", "截至2026-10-01生产100台KQ-Z112"):
            self.assertEqual(self.query(message)["status"], "needs_input")

    def test_explicit_as_of_is_business_date_anchor_not_future_snapshot(self):
        self.bom("V01", start="2026-01-01", end="2026-09-30")
        self.bom("V02", start="2026-10-01")
        self.stock("2026-09-20T00:00:00+00:00")
        self.stock()
        response = self.query("生产100台KQ-Z112 截至2026-09-25T00:00:00+00:00")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V01")
        self.assertEqual(response["structured_data"]["query"]["effective_date"], "2026-09-25")
        self.assertEqual(response["structured_data"]["query"]["as_of"], "2026-09-25T00:00:00+00:00")

    def test_without_fact_time_no_today_or_bom_start_date_default(self):
        self.bom()
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "needs_input")
        self.assertIn("没有明确的已发布业务时点", response["answer"])
        self.assertIsNone(response["structured_data"]["query"]["effective_date"])

    def test_relative_future_date_is_not_replaced_by_snapshot(self):
        self.bom()
        self.stock()
        response = self.query("下个月生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "needs_input")
        self.assertIn("具体的业务日期", response["answer"])

    def test_explicit_start_date_selects_bom_but_missing_start_is_never_inferred(self):
        self.bom()
        self.stock()
        response = self.query("KQ-Z112 生产100台的采购建议")
        self.assertEqual(response["status"], "needs_input")
        self.assertIn("计划开工日期", response["structured_data"]["missing_fields"])
        self.assertIsNone(response["structured_data"]["query"]["start_date"])
        resolver = self.service.orchestrator.context_resolver
        plan, _ = self.service.orchestrator.planner.plan("KQ-Z112 生产100台的采购建议 开工日期2026-10-20", {})
        resolved = resolver.resolve(plan, "KQ-Z112 生产100台的采购建议 开工日期2026-10-20")
        self.assertEqual(resolved.plan.entities.effective_date, "2026-10-20")
        self.assertEqual(resolved.plan.entities.start_date, "2026-10-20")

    def test_invalid_user_revision_not_replaced_with_valid_revision(self):
        self.bom()
        self.stock()
        response = self.query("生产100台KQ-Z112 使用V02")
        self.assertEqual(response["status"], "data_unavailable")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V02")

    def test_metadata_evidence_survives_service_restart(self):
        self.bom()
        self.stock()
        response = self.query("生产100台KQ-Z112可以吗")
        fresh = PersistentAgentService(AgentConversationRepository(self.fixture.store))
        fresh.enable_orchestrator()
        history = fresh.repository.history(self.session_id)
        self.assertEqual(history["turns"][0]["response"], response)
        reference = next(row for row in history["turns"][0]["fact_references"] if row["tool_name"] == "published_bom_context")
        revision = next(row for row in reference["result"]["data"]["resolutions"] if row["field"] == "revision")
        self.assertTrue(revision["provenance"]["source_file"])
        self.assertTrue(revision["provenance"]["import_batch_id"])
        self.assertTrue(revision["provenance"]["content_sha256"])
        self.assertEqual(fresh.query(self.session_id, "减少到50台呢")["status"], "ok")

    def test_auto_context_revalidated_when_a_conflicting_bom_is_published(self):
        self.bom()
        self.stock()
        self.assertEqual(self.query("生产100台KQ-Z112可以吗")["status"], "ok")
        self.bom("V02", start="2026-09-15")
        response = self.query("减少到50台呢")
        self.assertEqual(response["status"], "needs_input")
        self.assertIn("多个有效BOM版本", response["answer"])
        self.assertIsNone(response["structured_data"]["query"]["revision"])

    def test_explicit_choice_remains_explicit_in_follow_up(self):
        self.bom()
        self.bom("V02", start="2026-09-15")
        self.stock()
        self.assertEqual(self.query("生产100台KQ-Z112 使用V02")["status"], "ok")
        response = self.query("减少到50台呢")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V02")

    def test_clarification_can_be_resumed_with_only_a_revision(self):
        self.bom()
        self.bom("V02", start="2026-09-15")
        self.stock()
        self.assertEqual(self.query("生产100台KQ-Z112可以吗")["status"], "needs_input")
        response = self.query("使用V02")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query"]["revision"], "V02")
        self.assertEqual(response["structured_data"]["data"]["requested_quantity"], 100)

    def test_snapshot_metadata_orders_timestamps_with_offsets_correctly(self):
        self.stock("2026-10-01T01:00:00+08:00")
        self.stock("2026-09-30T23:00:00+00:00")
        latest = self.service.orchestrator.context_resolver.repository.latest_inventory_time()
        self.assertEqual(latest["snapshot_at"], "2026-09-30T23:00:00+00:00")

    def test_alias_is_exactly_resolved_before_bom_metadata_lookup(self):
        self.bom()
        self.stock()
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection,
                "INSERT INTO item_aliases (id, item_id, alias_code, alias_type, created_at) VALUES ('context-alias', ?, 'ALIAS-112', 'explicit', '2026-10-01T00:00:00+00:00')",
                (self.fixture.items["KQ-Z112"],))
        response = self.query("生产100台ALIAS-112可以吗")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["data"]["product"], "KQ-Z112")

    def test_explicit_new_product_cannot_reuse_resolved_old_context(self):
        self.bom()
        self.stock()
        self.query("生产100台KQ-Z112可以吗")
        response = self.query("生产100台MODULE可以吗")
        self.assertEqual(response["status"], "data_unavailable")
        self.assertIsNone(response["structured_data"]["query"]["revision"])

    def test_invalid_published_period_refuses_and_hides_internal_error(self):
        self.bom(start="2026-10-01", end="2026-09-01")
        self.stock()
        response = self.query("生产100台KQ-Z112可以吗")
        self.assertEqual(response["status"], "data_unavailable")
        self.assertNotIn("Invalid published", json.dumps(response))

    def test_api_without_revision_date_keeps_public_contract(self):
        self.bom()
        self.stock()
        response = TestClient(app).post("/api/v1/agent/query", json={"message": "生产100台KQ-Z112可以吗", "persist_session": True})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        UnifiedAgentResponse.model_validate(payload)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["intent"], "production_capacity")
        self.assertTrue(payload["structured_data"]["data"]["inventory_sufficient_for_requested"])

    def test_demo_uses_existing_context_and_has_no_enterprise_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = build_demo_scenario_agent(runtime_root=Path(directory))
            demo.enable_orchestrator()
            self.assertIsNone(demo.orchestrator.context_resolver)
            sid = demo.repository.create_session()["session_id"]
            response = demo.query(sid, "生产50台DEMO-PMC-01")
            self.assertTrue(response["structured_data"]["data"]["inventory_sufficient_for_requested"])
            self.assertNotIn("context_evidence", response["structured_data"])
            with self.assertRaises(ValueError):
                AgentOrchestrator(ToolRegistry(resolver=demo.tool_resolver, scope="demo_scenario_50_vs_100"),
                                  context_resolver=self.service.orchestrator.context_resolver)


if __name__ == "__main__":
    unittest.main()
