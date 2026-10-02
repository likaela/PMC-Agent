"""v1.13 合成 published facts、真实文件SQLite、隔进程恢复；LLM严格mock。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import app
from repositories.agent_conversation_repository import AgentConversationRepository, SessionConflict
from repositories.fact_store import SQLiteFactStore
from services.persistent_agent_service import PersistentAgentService, parse_enterprise_query
from tests import test_published_purchase_planning as purchase_fixtures


class PersistentAgentTests(unittest.TestCase):
    def setUp(self):
        fixture = purchase_fixtures.PublishedPurchasePlanningTests(methodName="test_moq_is_used_when_positive_requirement_is_smaller")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.repository = AgentConversationRepository(fixture.store)
        self.service = PersistentAgentService(self.repository)
        self.session = self.repository.create_session()["session_id"]
        self.client = TestClient(app)
        environment = patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{fixture.database.as_posix()}", "PMC_DATA_SOURCE": "demo"})
        environment.start()
        self.addCleanup(environment.stop)
        llm = patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"})
        llm.start()
        self.addCleanup(llm.stop)

    def _query(self, message):
        return self.service.query(self.session, message)

    def _prepare(self):
        self.fixture._prepare(stock="30")

    def test_creation_and_empty_history(self):
        history = self.repository.history(self.session)
        self.assertEqual(history["turns"], [])
        self.assertEqual(history["context_version"], 0)
        self.assertNotEqual(self.repository.create_session()["session_id"], self.session)

    def test_inventory_null_is_not_zero_and_source_is_saved(self):
        self.fixture._inventory({"MAT-001": None})
        result = self._query("查询 MAT-001 库存")
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["structured_data"]["data"]["available_qty"])
        self.assertIn("未知", result["answer"])
        turn = self.repository.history(self.session)["turns"][0]
        self.assertEqual(turn["response"], result)
        self.assertEqual(turn["user_query"], "查询 MAT-001 库存")
        reference = turn["fact_references"][0]
        self.assertEqual(reference["tool_name"], "published_inventory_query")
        for field in ("source_file", "content_sha256", "import_batch_id", "snapshot_at"):
            self.assertTrue(reference["provenance"][field])

    def test_context_survives_fresh_repository(self):
        self._prepare()
        self._query("查询 MAT-001 库存")
        fresh = PersistentAgentService(AgentConversationRepository(SQLiteFactStore(self.fixture.database)))
        result = fresh.query(self.session, "这个物料还有多少")
        self.assertEqual(result["structured_data"]["query"]["material_code"], "MAT-001")
        self.assertEqual(result["structured_data"]["data"]["on_hand_qty"], "30")

    def test_explicit_new_item_overrides_old_and_missing_stays_missing(self):
        self._prepare()
        self._query("查询 MAT-001 库存")
        result = self._query("查询 MAT-002 库存")
        self.assertEqual(result["status"], "data_unavailable")
        result = self._query("还有多少")
        self.assertEqual(result["structured_data"]["query"]["material_code"], "MAT-002")
        self.assertIsNone(result["structured_data"]["data"].get("on_hand_qty"))

    def test_new_unknown_item_does_not_revert_to_old_item(self):
        self._prepare()
        self._query("MAT-001库存")
        self.assertEqual(self._query("NO-999库存")["status"], "item_not_found")
        result = self._query("还有多少")
        self.assertEqual(result["status"], "item_not_found")
        self.assertEqual(result["structured_data"]["query"]["material_code"], "NO-999")

    def test_material_alias_is_resolved_before_context_is_saved(self):
        self._prepare()
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection,
                "INSERT INTO item_aliases (id, item_id, alias_code, alias_type, created_at) VALUES ('alias-test', ?, 'ALIAS-001', 'explicit', '2026-10-01T00:00:00+00:00')",
                (self.fixture.items["MAT-001"],))
        result = self._query("查询 ALIAS-001 库存")
        self.assertEqual(result["status"], "ok")
        context = self.repository.get_session(self.session)["context"]["fact"]
        self.assertEqual(context["material_code"], "MAT-001")

    def test_bom_and_effective_time_inherited_into_capacity(self):
        self._prepare()
        first = self._query("查询 PRODUCT V1 BOM 生效日期2026-10-01 截至2026-10-01T00:00:00+00:00")
        self.assertEqual(first["status"], "ok")
        result = self._query("还能生产多少？")
        self.assertEqual(result["intent"], "production_capacity")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structured_data"]["data"]["theoretical_max_quantity"], 30)
        self.assertEqual(result["structured_data"]["query"]["revision"], "V1")
        self.assertEqual(result["structured_data"]["query"]["effective_date"], "2026-10-01")

    def test_inventory_to_capacity_does_not_guess_revision(self):
        self._prepare()
        self._query("查询 PRODUCT 库存")
        result = self._query("还能生产多少？")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("BOM版本", result["structured_data"]["missing_fields"])
        result = self._query("V1 生效日期2026-10-01")
        self.assertEqual(result["status"], "ok")

    def test_new_product_cannot_inherit_old_version_or_date(self):
        self._prepare()
        self._query("PRODUCT V1 生效日期2026-10-01最多生产多少")
        result = self._query("MODULE能生产多少")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["structured_data"]["query"]["revision"])
        self.assertIsNone(result["structured_data"]["query"]["effective_date"])

    def test_explicit_time_inherits_but_current_resets_requested_time(self):
        self._prepare()
        self._query("MAT-001库存 截至2026-10-01T00:00:00+00:00")
        self._query("还有多少")
        self.assertEqual(self.repository.get_session(self.session)["context"]["fact"]["as_of"], "2026-10-01T00:00:00+00:00")
        self._query("现在还有多少")
        self.assertIsNone(self.repository.get_session(self.session)["context"]["fact"]["as_of"])

    def test_production_task_uses_only_published_tool(self):
        self._prepare()
        with patch("api.routes.agent.chat") as chat, patch("workflows.pmc_graph.run_pmc_workflow") as workflow:
            result = self._query("生产100台PRODUCT V1 生效日期2026-10-01")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(result["structured_data"]["data"]["materials"][0]["shortage_qty"], "70")
        chat.assert_not_called()
        workflow.assert_not_called()

    def test_production_and_fact_context_are_isolated(self):
        self._prepare()
        self._query("PRODUCT V1 生效日期2026-10-01生产100台")
        self._query("MAT-002库存")
        result = self._query("还能生产多少？")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["structured_data"]["query"]["material_code"], "MAT-002")
        self.assertIsNone(result["structured_data"]["query"]["revision"])

    def test_omitted_inventory_object_cannot_revive_inactive_old_material(self):
        self._prepare()
        self._query("MAT-001库存")
        self._query("PRODUCT V1 生效日期2026-10-01生产100台")
        result = self._query("这个料有没有库存")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["structured_data"]["query"]["material_code"])

    def test_purchase_planning_uses_existing_service_results(self):
        self._prepare()
        result = self._query("PRODUCT V1 生产100台 采购建议 生效日期2026-10-01 开工日期2026-10-20 截至2026-10-01T00:00:00+00:00")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structured_data"]["data"], self.fixture._query()["data"])
        self.assertEqual(result["provenance"], self.fixture._query()["provenance"])
        self.assertIn("70", result["answer"])

    def test_purchase_missing_fields_are_not_guessed(self):
        self._prepare()
        result = self._query("PRODUCT V1 采购建议")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("计划开工日期", result["structured_data"]["missing_fields"])
        self.assertEqual(self.repository.history(self.session)["turns"][0]["fact_references"], [])

    def test_purchase_clarification_can_be_completed_across_turns(self):
        self._prepare()
        self.assertEqual(self._query("PRODUCT V1 采购建议 生效日期2026-10-01")["status"], "needs_input")
        self.assertEqual(self._query("一百台")["status"], "needs_input")
        result = self._query("开工日期2026-10-20 截至2026-10-01T00:00:00+00:00")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structured_data"]["query"]["quantity"], 100)
        self.assertEqual(result["structured_data"]["data"], self.fixture._query()["data"])

    def test_missing_inventory_refuses_without_zero(self):
        result = self._query("MAT-001库存")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIn("没有已发布库存", result["answer"])
        self.assertIsNone(result["structured_data"]["data"].get("on_hand_qty"))

    def test_missing_bom_and_inbound_refuse(self):
        for message in ("PRODUCT V1 BOM", "MAT-001在途"):
            result = self._query(message)
            self.assertEqual(result["status"], "data_unavailable")
            self.assertIn("当前事实库没有", result["answer"])

    def test_two_sessions_do_not_share_context(self):
        self._prepare()
        self._query("MAT-001库存")
        other = self.repository.create_session()["session_id"]
        result = self.service.query(other, "还有多少")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(len(self.repository.history(other)["turns"]), 1)

    def test_stale_write_conflict_has_no_partial_turn(self):
        session = self.repository.get_session(self.session)
        response = dict(intent="clarification", status="needs_input", answer="补充条件", structured_data=None, provenance=None, warnings=[])
        self.repository.append_turn(session, "first", response, session["context"], [])
        with self.assertRaises(SessionConflict):
            self.repository.append_turn(session, "second", response, session["context"], [])
        self.assertEqual(len(self.repository.history(self.session)["turns"]), 1)

    def test_real_concurrent_writes_have_one_success_and_one_conflict(self):
        barrier = Barrier(2)

        def submit(message):
            repository = AgentConversationRepository(SQLiteFactStore(self.fixture.database))
            session = repository.get_session(self.session)
            barrier.wait(timeout=5)
            try:
                repository.append_turn(session, message, {}, session["context"], [])
                return "saved"
            except SessionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, ["first", "second"]))
        self.assertEqual(sorted(results), ["conflict", "saved"])
        self.assertEqual(len(self.repository.history(self.session)["turns"]), 1)

    def test_bom_revision_is_saved_with_source_reference(self):
        self._prepare()
        result = self._query("查询 PRODUCT V1 BOM")
        reference = self.repository.history(self.session)["turns"][0]["fact_references"][0]
        self.assertEqual(reference["tool_name"], "published_bom_query")
        self.assertEqual(reference["provenance"]["bom_version"], "V1")
        self.assertEqual(reference["result"]["data"], result["structured_data"]["data"])

    def test_valid_llm_only_classifies_literal_parameters(self):
        self._prepare()
        mock = MagicMock()
        mock.with_structured_output.return_value.invoke.return_value = {"query_type": "inventory", "material_code": "MAT-001"}
        with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "services.persistent_agent_service.get_llm", return_value=mock):
            result = self._query("帮我核实 MAT-001")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structured_data"]["data"]["on_hand_qty"], "30")
        self.assertEqual(result["structured_data"]["parser_source"], "llm")

    def test_reference_insert_failure_rolls_back_entire_turn(self):
        session = self.repository.get_session(self.session)
        with self.assertRaises(KeyError):
            self.repository.append_turn(session, "failed", {}, {"changed": True}, [{}])
        self.assertEqual(self.repository.history(self.session)["turns"], [])
        self.assertEqual(self.repository.get_session(self.session)["context_version"], 0)

    def test_process_restart_restores_context_and_turns(self):
        self._prepare()
        self._query("MAT-001库存")
        program = (
            "import json; from repositories.fact_store import create_fact_store; "
            "from repositories.agent_conversation_repository import AgentConversationRepository; "
            "from services.persistent_agent_service import PersistentAgentService; "
            f"r=AgentConversationRepository(create_fact_store()); s={self.session!r}; "
            "a=PersistentAgentService(r).query(s,'还有多少'); "
            "print(json.dumps({'result':a,'count':len(r.history(s)['turns'])}))"
        )
        process = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["result"]["structured_data"]["data"]["on_hand_qty"], "30")

    def test_api_create_query_history_recovers_identical_response(self):
        self._prepare()
        created = self.client.post("/api/v1/agent/sessions")
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["session_id"]
        response = self.client.post("/api/v1/agent/query", json={"session_id": session_id, "message": "MAT-001库存"})
        self.assertEqual(response.status_code, 200)
        history = TestClient(app).get(f"/api/v1/agent/sessions/{session_id}").json()
        self.assertEqual(history["turns"][0]["response"], response.json())

    def test_api_can_create_session_on_first_query(self):
        self._prepare()
        result = self.client.post("/api/v1/agent/query", json={"persist_session": True, "message": "MAT-001库存"})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["session_id"])

    def test_api_unknown_session_returns_sanitized_404(self):
        for method, path, body in (("GET", "/api/v1/agent/sessions/not-found", None),
                                   ("POST", "/api/v1/agent/query", {"session_id": "not-found", "message": "MAT-001库存"})):
            response = self.client.request(method, path, json=body)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "SESSION_NOT_FOUND")

    def test_api_rejects_mixed_demo_and_enterprise_session(self):
        response = self.client.post("/api/v1/agent/query", json={"message": "MAT-001库存", "session_id": self.session, "workflow_id": "demo"})
        self.assertEqual(response.status_code, 422)

    def test_history_pagination_and_immutable_references(self):
        self._prepare()
        first = self._query("MAT-001库存")
        self._query("还有多少")
        with self.fixture.store.transaction() as connection:
            self.fixture.store.execute(connection, "UPDATE inventory_facts SET on_hand_qty = '999'")
        history = self.repository.history(self.session, after=0, limit=1)
        self.assertEqual(history["turns"][0]["response"]["structured_data"]["data"], first["structured_data"]["data"])
        self.assertEqual(len(self.repository.history(self.session, after=1)["turns"]), 1)

    def test_tool_exception_is_sanitized_and_audited(self):
        tool = MagicMock(name="tool")
        tool.name = "published_inventory_query"
        tool.invoke.side_effect = RuntimeError("private password traceback")
        with patch("services.persistent_agent_service.get_fact_query_tool", return_value=tool):
            result = self._query("MAT-001库存")
        self.assertEqual(result["status"], "query_failed")
        self.assertNotIn("password", json.dumps(self.repository.history(self.session)))

    def test_invalid_quantity_does_not_reuse_old_valid_quantity(self):
        self._prepare()
        self._query("PRODUCT V1 生效日期2026-10-01生产100台")
        for message in ("减少到-5台", "生产0台", "生产1.5台"):
            self.assertEqual(self._query(message)["status"], "needs_input")

    def test_llm_failure_or_hallucinated_parameters_do_not_create_facts(self):
        for candidate in ({"query_type": "inventory", "material_code": "MAT-001"}, "invalid json"):
            mock = MagicMock()
            mock.with_structured_output.return_value.invoke.return_value = candidate
            with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "ok"}), patch(
                "services.persistent_agent_service.get_llm", return_value=mock):
                result = self._query("随便问点东西")
            self.assertEqual(result["status"], "needs_input")
            self.assertIsNone(result["provenance"])
        with patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "services.persistent_agent_service.get_llm", side_effect=TimeoutError("secret")):
            intent, source = parse_enterprise_query("随便问点东西")
        self.assertEqual(intent.query_type, "clarification")
        self.assertEqual(source, "rule_fallback")

    def test_rules_call_no_llm_for_explicit_business_queries(self):
        with patch("services.persistent_agent_service.get_llm") as llm:
            result = self._query("MAT-001库存")
        self.assertEqual(result["status"], "data_unavailable")
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
