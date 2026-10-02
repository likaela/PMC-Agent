"""Phase 2: real isolated published demo facts, mocked LLM, unchanged public API."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from agents.evidence import EvidenceCollector
from agents.orchestrator import AgentOrchestrator
from agents.planner import AgentPlan, AgentPlanner
from agents.response_generator import NO_EVIDENCE, ResponseGenerator
from agents.tool_registry import ToolRegistry
from api.app import app
from api.schemas.agent import UnifiedAgentResponse
from repositories.demo_scenario_repository import SCENARIO_ID
from services.demo_scenario_agent_service import build_demo_scenario_agent


def proposal(intent, code=None, quantity=None, tools=None, **fields):
    primary = {"inventory": "inventory_query", "inventory_batches": "batch_inventory_query", "bom": "bom_query",
               "production_capacity": "production_analysis", "purchase_planning": "purchase_plan"}
    return dict(intent=intent, entities=dict(material_code=code, quantity=quantity, **fields),
                required_tools=tools if tools is not None else [primary[intent]], missing_parameters=[])


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = build_demo_scenario_agent(runtime_root=self.root)
        self.session_id = self.service.repository.create_session()["session_id"]
        self.payload = proposal("production_capacity", "DEMO-PMC-01", 50)
        self.reply = {"statement_ids": ["e0"], "closing": ""}
        self.llm = MagicMock()

        def structured(schema, **kwargs):
            model = MagicMock()
            model.invoke.side_effect = lambda messages: self.payload if schema is AgentPlan else self.reply
            return model

        self.llm.with_structured_output.side_effect = structured
        self.factory = Mock(return_value=self.llm)
        self.planner = AgentPlanner(llm_factory=self.factory, llm_status=lambda: {"status": "ok"})
        self.generator = ResponseGenerator(llm_factory=self.factory, llm_status=lambda: {"status": "ok"})
        self.registry = ToolRegistry(resolver=self.service.tool_resolver, scope=SCENARIO_ID)
        self.service.orchestrator = AgentOrchestrator(self.registry, planner=self.planner, response_generator=self.generator)
        guard = patch("services.persistent_agent_service.get_llm_configuration_status", return_value={"status": "warning"})
        guard.start()
        self.addCleanup(guard.stop)

    def query(self, message):
        response = self.service.query(self.session_id, message)
        UnifiedAgentResponse.model_validate(response)
        return response

    def history(self):
        return self.service.repository.history(self.session_id)

    def test_planner_selects_production_tool_and_50_demo_matches_existing_calculation(self):
        response = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(response["structured_data"]["parser_source"], "llm")
        self.assertEqual(response["structured_data"]["response_source"], "llm")
        reference = self.history()["turns"][0]["fact_references"][0]
        self.assertEqual(reference["tool_name"], "demo_production_capacity_query")
        expected = self.registry.resolve("production_analysis").invoke(reference["query"])
        self.assertEqual(response["structured_data"]["data"], expected["data"])
        self.assertEqual(response["provenance"]["scenario_id"], SCENARIO_ID)

    def test_inventory_uses_existing_tool_with_decimal_strings(self):
        self.payload = proposal("inventory", "DEMO-BOARD-01")
        response = self.query("查询DEMO-BOARD-01库存")
        self.assertEqual(response["structured_data"]["data"]["on_hand_qty"], "75")
        self.assertEqual(self.history()["turns"][0]["fact_references"][0]["tool_name"], "demo_inventory_query")
        self.assertIn("75", response["answer"])

    def test_purchase_plan_uses_moq_cost_and_no_stock_mutation(self):
        self.payload = proposal("purchase_planning", "DEMO-PMC-01", 100)
        before = self.registry.resolve("inventory_query").invoke({"material_code": "DEMO-BOARD-01"})
        response = self.query("生产100台DEMO-PMC-01的采购建议")
        self.assertEqual(response["status"], "ok")
        data = response["structured_data"]["data"]
        self.assertEqual(len(data["recommendations"]), 4)
        board = next(row for row in data["recommendations"] if row["material"] == "DEMO-BOARD-01")
        self.assertEqual(board["suggested_purchase_qty"], "30")
        reference = self.history()["turns"][0]["fact_references"][0]
        self.assertEqual(reference["tool_name"], "demo_purchase_planning_query")
        self.assertEqual(data, self.registry.resolve("purchase_plan").invoke(reference["query"])["data"])
        after = self.registry.resolve("inventory_query").invoke({"material_code": "DEMO-BOARD-01"})
        self.assertEqual(before, after)

    def test_batch_and_bom_aliases(self):
        for message, intent, code, name in (
            ("DEMO-BOARD-01有哪些批次", "inventory_batches", "DEMO-BOARD-01", "demo_inventory_batches_query"),
            ("查询DEMO-PMC-01 V01 BOM", "bom", "DEMO-PMC-01", "demo_bom_query"),
        ):
            self.payload = proposal(intent, code)
            result = self.query(message)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(self.history()["turns"][-1]["fact_references"][0]["tool_name"], name)

    def test_invalid_quantity_and_date_execute_no_tool(self):
        with patch.object(self.registry, "resolve", wraps=self.registry.resolve) as resolve:
            for message in ("生产0台DEMO-PMC-01", "生产-5台DEMO-PMC-01", "生产1.5台DEMO-PMC-01",
                            "生产50台DEMO-PMC-01 生效日期2026-02-30"):
                self.assertEqual(self.query(message)["status"], "needs_input")
        resolve.assert_not_called()
        self.factory.assert_not_called()
        self.assertTrue(all(not turn["fact_references"] for turn in self.history()["turns"]))

    def test_deepseek_failure_falls_back_without_api_error(self):
        self.factory.side_effect = TimeoutError("private key traceback")
        result = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(result["structured_data"]["parser_source"], "rule_fallback")
        self.assertNotIn("private", json.dumps(self.history()))

    def test_invalid_json_falls_back(self):
        self.payload = "not JSON"
        result = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["structured_data"]["parser_source"], "rule_fallback")

    def test_json_string_plan_is_validated(self):
        self.payload = json.dumps(self.payload)
        result = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(result["structured_data"]["parser_source"], "llm")

    def test_model_cannot_add_calculations_or_replace_explicit_quantity(self):
        for invalid in (
            {**proposal("production_capacity", "DEMO-PMC-01", 50), "shortage": 25},
            proposal("production_capacity", "DEMO-PMC-01", 999),
            proposal("production_capacity", "OTHER-01", 50),
        ):
            self.payload = invalid
            result = self.query("生产50台DEMO-PMC-01")
            self.assertEqual(result["structured_data"]["parser_source"], "rule_fallback")
            self.assertEqual(result["structured_data"]["data"]["requested_quantity"], 50)

    def test_unregistered_or_mismatched_tool_cannot_execute(self):
        for tools in (["execute_sql"], ["bom_query"], ["production_analysis", "production_analysis"]):
            self.payload = proposal("inventory", "DEMO-BOARD-01", tools=tools)
            result = self.query("查询DEMO-BOARD-01库存")
            self.assertEqual(result["structured_data"]["parser_source"], "rule_fallback")
            self.assertEqual(self.history()["turns"][-1]["fact_references"][0]["tool_name"], "demo_inventory_query")

    def test_reply_cannot_introduce_numbers_forecasts_or_free_text(self):
        self.reply = {"statement_ids": ["e0"], "answer": "预计下个月可生产9999台", "closing": ""}
        result = self.query("生产50台DEMO-PMC-01")
        self.assertNotIn("9999", result["answer"])
        self.assertNotIn("预计", result["answer"])
        self.assertIn("75", result["answer"])
        self.assertEqual(result["structured_data"]["response_source"], "rule_fallback")

    def test_unknown_evidence_cannot_be_omitted_or_changed_to_zero(self):
        self.payload = proposal("inventory", "NOT-FOUND-01")
        result = self.query("查询NOT-FOUND-01库存")
        self.assertEqual(result["status"], "item_not_found")
        self.assertIn(NO_EVIDENCE, result["answer"])
        self.assertNotIn("库存为0", result["answer"])

    def test_null_available_stays_null_in_evidence_and_answer(self):
        tool = MagicMock()
        tool.name = "test_inventory"
        tool.invoke.return_value = dict(status="ok", query={"material_code": "DEMO-BOARD-01"},
            data={"on_hand_qty": "75", "available_qty": None, "reserved_qty": None},
            completeness={"on_hand_qty": True, "available_qty": False, "reserved_qty": False},
            provenance={"source_file": "synthetic.xlsx"}, warnings=["可用库存未知"])
        self.registry._resolver = lambda kind: tool
        self.payload = proposal("inventory", "DEMO-BOARD-01")
        response = self.query("DEMO-BOARD-01库存")
        self.assertIsNone(response["structured_data"]["data"]["available_qty"])
        self.assertIn("未知", response["answer"])
        self.assertIsNone(self.history()["turns"][0]["fact_references"][0]["result"]["data"]["available_qty"])

    def test_new_product_does_not_inherit_demo_version_and_date(self):
        self.payload = proposal("production_capacity", "OTHER-PRODUCT-01", 50, revision="V01",
                                effective_date="2026-10-02")
        with patch.object(self.registry, "resolve", wraps=self.registry.resolve) as resolve:
            result = self.query("生产50台OTHER-PRODUCT-01")
        resolve.assert_not_called()
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["structured_data"]["query"]["revision"])

    def test_multiple_tools_record_each_evidence_and_keep_primary_card(self):
        self.payload = proposal("production_capacity", "DEMO-PMC-01", 50, tools=["bom_query", "production_analysis"])
        self.reply = {"statement_ids": ["e1", "e0"], "closing": ""}
        response = self.query("生产50台DEMO-PMC-01")
        self.assertTrue(response["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(len(self.history()["turns"][0]["fact_references"]), 2)
        self.assertEqual(len(response["provenance"]), 2)
        self.assertEqual(len(response["structured_data"]["completed_steps"]), 2)
        self.assertEqual(response["structured_data"]["response_source"], "llm")

    def test_missing_parameters_for_secondary_tool_block_entire_plan(self):
        self.payload = proposal("production_capacity", "DEMO-PMC-01", 50, tools=["production_analysis", "purchase_plan"])
        context = self.service.repository.get_session(self.session_id)["context"]
        context["production"]["start_date"] = None
        result = self.service.orchestrator.run("生产50台DEMO-PMC-01", context)
        self.assertEqual(result.response["status"], "needs_input")
        self.assertEqual(result.references, [])

    def test_tool_failure_is_sanitized_and_stops_dependent_tools(self):
        failing = MagicMock()
        failing.name = "test_bom"
        failing.invoke.side_effect = RuntimeError("private password traceback")
        self.registry._resolver = Mock(return_value=failing)
        self.payload = proposal("production_capacity", "DEMO-PMC-01", 50, tools=["bom_query", "production_analysis"])
        result = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(result["status"], "query_failed")
        self.assertIsNone(result["structured_data"]["data"])
        self.assertEqual(len(self.history()["turns"][0]["fact_references"]), 1)
        self.assertNotIn("password", json.dumps(self.history()))
        self.registry._resolver.assert_called_once()

    def test_demo_isolation_never_uses_enterprise_store_factory(self):
        with patch("repositories.fact_store.create_fact_store", side_effect=AssertionError("enterprise access")):
            result = self.query("生产50台DEMO-PMC-01")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["provenance"]["synthetic"])
        with self.assertRaises(ValueError):
            AgentOrchestrator(ToolRegistry(), planner=self.planner).run("生产50台DEMO-PMC-01", self.history()["context"])
        with self.assertRaises(ValueError):
            ToolRegistry(scope=SCENARIO_ID)

    def test_persistent_history_and_fresh_service_restore_context(self):
        self.payload = proposal("production_capacity", "DEMO-PMC-01", 100)
        first = self.query("生产100台DEMO-PMC-01")
        self.assertEqual(self.history()["turns"][0]["response"], first)
        fresh = build_demo_scenario_agent(runtime_root=self.root)
        fresh.enable_orchestrator()
        second = fresh.query(self.session_id, "减少到50台呢")
        self.assertTrue(second["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertEqual(second["structured_data"]["data"]["requested_quantity"], 50)
        self.assertEqual(len(fresh.repository.history(self.session_id)["turns"]), 2)

    def test_existing_inbound_path_remains_available(self):
        result = self.query("查询DEMO-BOARD-01在途")
        self.assertEqual(result["intent"], "inbound")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.history()["turns"][0]["fact_references"][0]["tool_name"], "demo_inbound_query")

    def test_api_contract_and_history_remain_valid_without_frontend_change(self):
        client = TestClient(app)
        with patch("services.demo_scenario_agent_service.build_demo_scenario_agent",
                   side_effect=lambda: build_demo_scenario_agent(runtime_root=self.root)):
            response = client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "message": "生产50台DEMO-PMC-01"})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            UnifiedAgentResponse.model_validate(result)
            self.assertEqual(result["intent"], "production_capacity")
            self.assertTrue(result["structured_data"]["data"]["inventory_sufficient_for_requested"])
            history = client.get(f"/api/v1/agent/sessions/{result['session_id']}", params={"scenario_id": SCENARIO_ID})
            self.assertEqual(history.json()["turns"][0]["response"], result)
            self.assertEqual(len(result["structured_data"]["completed_steps"]), 1)


class EvidenceAndGeneratorTests(unittest.TestCase):
    def test_no_evidence_refuses_and_does_not_call_llm(self):
        factory = Mock()
        self.assertEqual(ResponseGenerator(llm_factory=factory).generate([], []), (NO_EVIDENCE, "deterministic"))
        factory.assert_not_called()

    def test_collector_keeps_copy_provenance_strings_and_null(self):
        output = dict(status="ok", query={}, data={"on_hand_qty": "12.50", "available_qty": None},
                      completeness={"available_qty": False}, provenance={"source_file": "fixture.xlsx"}, warnings=[])
        collector = EvidenceCollector()
        record = collector.collect("inventory", {}, output)
        output["data"]["on_hand_qty"] = "999"
        record.output["data"]["on_hand_qty"] = "888"
        self.assertEqual(collector.records[0].as_dict()["output"]["data"]["on_hand_qty"], "12.50")
        self.assertIsNone(collector.records[0].output["data"]["available_qty"])
        self.assertEqual(collector.records[0].provenance["source_file"], "fixture.xlsx")

    def test_malformed_output_is_not_evidence(self):
        collector = EvidenceCollector()
        for output in ("text", {"status": "ok"}, dict(status="ok", query={}, data=None, completeness={}, provenance=None, warnings=[])):
            with self.assertRaises(ValueError):
                collector.collect("inventory", {}, output)
        self.assertEqual(collector.records, [])


if __name__ == "__main__":
    unittest.main()
