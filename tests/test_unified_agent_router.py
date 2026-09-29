"""新统一入口对既有 PMC Chat 与独立事实 Agent 的分流回归。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.agent_intent_router import IntentExtraction, route_agent_message
from services.inventory_import_service import InventoryImportService
from tests.test_inventory_fact_import import _create_inventory_workbook, _seed_item
from workflows.pmc_graph import get_pmc_workflow_state


def fact_result(status: str = "ok", *, data: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": status,
        "query": {"material_code": "MAT-001"},
        "data": data,
        "completeness": {"on_hand_qty": status == "ok", "available_qty": False},
        "provenance": (
            {
                "source_file": "synthetic.xlsx",
                "import_batch_id": "batch-1",
                "snapshot_id": "snapshot-1",
                "snapshot_at": "2026-09-20T00:00:00+00:00",
                "bom_version": "V1",
            }
            if status == "ok"
            else None
        ),
        "warnings": ["可用数量未知"] if status == "ok" else [],
        "query_type": "inventory",
        "tool_name": "published_inventory_query",
        "parser_source": "rule_fallback",
        "answer": "当前事实库没有对应信息。" if status != "ok" else "MAT-001 在库 7，可用数量未知。",
    }


class UnifiedAgentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.environment = patch.dict(os.environ, {"PMC_DATA_SOURCE": "demo"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.router_llm = patch(
            "services.agent_intent_router.get_llm_configuration_status",
            return_value={"status": "warning"},
        )
        self.router_llm.start()
        self.addCleanup(self.router_llm.stop)
        self.fact_llm = patch(
            "agents.fact_query_agent.get_llm_configuration_status",
            return_value={"status": "warning"},
        )
        self.fact_llm.start()
        self.addCleanup(self.fact_llm.stop)

    def test_production_task_still_enters_existing_pmc_workflow(self) -> None:
        with patch("api.routes.agent.run_fact_query_agent") as fact_agent:
            response = self.client.post(
                "/api/v1/agent/query",
                json={"message": "我要生产100台KQ-Z112"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "pmc_analysis")
        self.assertEqual(payload["status"], "ok")
        workflow_id = payload["structured_data"]["workflow_id"]
        self.assertEqual(payload["structured_data"]["parsed_task"]["quantity"], 100)
        self.assertEqual(get_pmc_workflow_state(workflow_id)["product"], "KQ-Z112")
        self.assertEqual(get_pmc_workflow_state(workflow_id)["completed_nodes"].count("bom_analysis"), 1)
        fact_agent.assert_not_called()

    def test_existing_explanation_and_scenario_context_are_reused(self) -> None:
        initial = self.client.post(
            "/api/v1/agent/query", json={"message": "我要生产100台KQ-Z112"}
        ).json()
        workflow_id = initial["structured_data"]["conversation_workflow_id"]
        before = get_pmc_workflow_state(workflow_id)
        why = self.client.post(
            "/api/v1/agent/query",
            json={"message": "为什么不能生产？", "workflow_id": workflow_id},
        )
        reduced = self.client.post(
            "/api/v1/agent/query",
            json={"message": "减少到50台呢？", "workflow_id": workflow_id},
        )
        self.assertEqual(why.status_code, 200)
        self.assertEqual(reduced.status_code, 200)
        self.assertEqual(why.json()["structured_data"]["turn_type"], "explanation")
        self.assertEqual(reduced.json()["structured_data"]["turn_type"], "scenario")
        self.assertEqual(get_pmc_workflow_state(workflow_id)["completed_nodes"], before["completed_nodes"])

    def test_inventory_question_routes_only_to_fact_query_agent(self) -> None:
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent", return_value=fact_result(data={"on_hand_qty": "7", "available_qty": None})
        ) as fact_agent:
            response = self.client.post(
                "/api/v1/agent/query", json={"message": "查询 MAT-001 库存"}
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "fact_query")
        self.assertEqual(payload["structured_data"]["data"]["on_hand_qty"], "7")
        self.assertIsNone(payload["structured_data"]["data"]["available_qty"])
        self.assertEqual(payload["provenance"]["snapshot_id"], "snapshot-1")
        self.assertEqual(payload["provenance"]["import_batch_id"], "batch-1")
        fact_agent.assert_called_once_with("查询 MAT-001 库存")
        pmc_chat.assert_not_called()

    def test_real_published_inventory_provenance_survives_api_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            database_path = directory / "facts.db"
            repository = FactRepository(SQLiteFactStore(database_path))
            repository.migrate()
            _seed_item(repository, "MAT-001")
            workbook = _create_inventory_workbook(
                directory / "synthetic.xlsx", [["S1", "L1", "MAT-001", "B1", 7]]
            )
            importer = InventoryImportService(repository)
            batch = importer.stage_inventory(
                workbook, snapshot_at=datetime(2026, 9, 20, tzinfo=UTC)
            )
            importer.publish(batch.import_batch_id)
            with patch.dict(
                os.environ,
                {"PMC_FACT_DATABASE_URL": f"sqlite:///{database_path.as_posix()}"},
            ):
                response = self.client.post(
                    "/api/v1/agent/query", json={"message": "查询 MAT-001 库存"}
                )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["structured_data"]["data"]["on_hand_qty"], "7")
            self.assertIsNone(payload["structured_data"]["data"]["available_qty"])
            self.assertEqual(payload["provenance"]["import_batch_id"], batch.import_batch_id)
            self.assertTrue(payload["provenance"]["snapshot_at"])
            self.assertEqual(payload["provenance"]["source_file"], "synthetic.xlsx")

    def test_bom_question_routes_to_fact_query_agent(self) -> None:
        result = fact_result(data={"revision": "V1", "lines": []})
        result["query_type"] = "bom"
        result["provenance"]["bom_version"] = "V1"
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent", return_value=result
        ) as fact_agent:
            response = self.client.post(
                "/api/v1/agent/query", json={"message": "查询 PARENT-1 V1 的 BOM"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "fact_query")
        self.assertEqual(response.json()["provenance"]["bom_version"], "V1")
        fact_agent.assert_called_once()
        pmc_chat.assert_not_called()

    def test_inbound_question_routes_to_fact_query_agent(self) -> None:
        result = fact_result("data_unavailable")
        result["query_type"] = "inbound"
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent", return_value=result
        ) as fact_agent:
            response = self.client.post(
                "/api/v1/agent/query", json={"message": "查询 MAT-001 在途"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "fact_query")
        self.assertEqual(response.json()["status"], "data_unavailable")
        fact_agent.assert_called_once()
        pmc_chat.assert_not_called()

    def test_no_fact_returns_unavailable_without_fabricated_answer(self) -> None:
        with patch("api.routes.agent.run_fact_query_agent", return_value=fact_result("data_unavailable")):
            response = self.client.post(
                "/api/v1/agent/query", json={"message": "查询 MAT-001 库存"}
            )
        payload = response.json()
        self.assertEqual(payload["status"], "data_unavailable")
        self.assertIsNone(payload["structured_data"]["data"])
        self.assertIsNone(payload["provenance"])
        self.assertIn("当前事实库没有对应信息", payload["answer"])

    def test_llm_failure_falls_back_to_rule_classification(self) -> None:
        with patch("services.agent_intent_router.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "services.agent_intent_router._invoke_llm_classification", side_effect=TimeoutError("private error")
        ):
            decision = route_agent_message("查询 MAT-001 库存")
        self.assertEqual(decision, {"intent": "fact_query", "parser_source": "rule_fallback"})

    def test_invalid_llm_intent_cannot_override_explicit_rule(self) -> None:
        with patch("services.agent_intent_router.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "services.agent_intent_router._invoke_llm_classification",
            return_value=IntentExtraction(intent="pmc_analysis"),
        ):
            decision = route_agent_message("查询 MAT-001 库存")
        self.assertEqual(decision, {"intent": "fact_query", "parser_source": "rule_override"})

    def test_mixed_intent_asks_clarification_without_calling_either_path(self) -> None:
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent"
        ) as fact_agent:
            response = self.client.post(
                "/api/v1/agent/query",
                json={"message": "查 MAT-001 库存并判断能否生产100台"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "clarification")
        self.assertEqual(response.json()["status"], "needs_input")
        pmc_chat.assert_not_called()
        fact_agent.assert_not_called()

    def test_unrecognized_message_does_not_guess_or_call_tools(self) -> None:
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent"
        ) as fact_agent:
            response = self.client.post("/api/v1/agent/query", json={"message": "你好"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "needs_input")
        pmc_chat.assert_not_called()
        fact_agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
