"""独立受控查询 Agent 的路由、Tool 调用和无事实拒答。"""

from __future__ import annotations

import unittest
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agents.fact_query_agent import FactQueryIntent, run_fact_query_agent
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.inventory_import_service import InventoryImportService
from tests.test_inventory_fact_import import _create_inventory_workbook, _seed_item
from tools.agent_tools import ALL_AGENT_TOOLS
from tools.fact_query_registry import FACT_QUERY_TOOL_REGISTRY
from tools.fact_query_tools import FACT_QUERY_TOOLS


class FakeTool:
    def __init__(self, name: str, result: dict[str, object]) -> None:
        self.name = name
        self.result = result
        self.calls: list[dict[str, object]] = []

    def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(arguments)
        return self.result


def tool_result(
    status: str = "ok",
    *,
    data: dict[str, object] | None = None,
    completeness: dict[str, bool] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "query": {"material_code": "MAT-001", "resolved_material_code": "MAT-001"},
        "data": data,
        "completeness": completeness or {},
        "provenance": {"source_file": "synthetic.xlsx", "import_batch_id": "batch-1"} if status == "ok" else None,
        "warnings": [],
    }


class FactQueryAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm_disabled = patch(
            "agents.fact_query_agent.get_llm_configuration_status",
            return_value={"status": "warning"},
        )
        self.llm_disabled.start()
        self.addCleanup(self.llm_disabled.stop)

    def _run_with_tool(self, message: str, result: dict[str, object]) -> tuple[dict[str, object], FakeTool]:
        fake = FakeTool("controlled_fact_tool", result)
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake):
            response = run_fact_query_agent(message)
        return response, fake

    def test_registry_is_independent_of_existing_demo_tools(self) -> None:
        self.assertEqual(set(FACT_QUERY_TOOL_REGISTRY), {"inventory", "inventory_batches", "bom", "inbound"})
        self.assertEqual(
            {tool.name for tool in FACT_QUERY_TOOL_REGISTRY.values()},
            {tool.name for tool in FACT_QUERY_TOOLS},
        )
        self.assertTrue(
            {tool.name for tool in ALL_AGENT_TOOLS}.isdisjoint(
                {tool.name for tool in FACT_QUERY_TOOL_REGISTRY.values()}
            )
        )

    def test_inventory_intent_calls_inventory_tool(self) -> None:
        response, tool = self._run_with_tool(
            "查一下 MAT-001 库存",
            tool_result(
                data={"on_hand_qty": "12", "available_qty": None, "reserved_qty": None},
                completeness={"on_hand_qty": True, "available_qty": False, "reserved_qty": False},
            ),
        )
        self.assertEqual(response["query_type"], "inventory")
        self.assertEqual(tool.calls, [{"material_code": "MAT-001", "as_of": None}])
        self.assertEqual(response["data"]["on_hand_qty"], "12")
        self.assertIn("来源", response["answer"])

    def test_agent_queries_real_published_inventory_fact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            database_path = directory / "facts.db"
            repository = FactRepository(SQLiteFactStore(database_path))
            repository.migrate()
            _seed_item(repository, "MAT-001")
            workbook = _create_inventory_workbook(
                directory / "synthetic.xlsx",
                [["S1", "L1", "MAT-001", "B1", 7]],
            )
            importer = InventoryImportService(repository)
            batch = importer.stage_inventory(
                workbook,
                snapshot_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
            importer.publish(batch.import_batch_id)
            with patch.dict(
                os.environ,
                {"PMC_FACT_DATABASE_URL": f"sqlite:///{database_path.as_posix()}"},
            ):
                response = run_fact_query_agent("查询 MAT-001 库存")
            self.assertEqual(response["status"], "ok")
            self.assertEqual(response["tool_name"], "published_inventory_query")
            self.assertEqual(response["data"]["on_hand_qty"], "7")
            self.assertIsNone(response["data"]["available_qty"])
            self.assertEqual(response["provenance"]["import_batch_id"], batch.import_batch_id)

    def test_inventory_batches_calls_batch_tool(self) -> None:
        response, tool = self._run_with_tool(
            "MAT-001 有哪些库存批次？",
            tool_result(data={"batches": [{"batch_no": "B1", "location": "L1", "on_hand_qty": "2"}]}),
        )
        self.assertEqual(response["query_type"], "inventory_batches")
        self.assertEqual(tool.calls[0]["material_code"], "MAT-001")
        self.assertIn("B1", response["answer"])

    def test_bom_intent_calls_bom_tool_with_explicit_revision(self) -> None:
        response, tool = self._run_with_tool(
            "查询 PARENT-1 V1 的 BOM",
            tool_result(data={"revision": "V1", "lines": [{"child_item": {"material_code": "MAT-001"}, "qty_per": "2"}]}),
        )
        self.assertEqual(response["query_type"], "bom")
        self.assertEqual(tool.calls, [{"parent_material_code": "PARENT-1", "revision": "V1"}])
        self.assertIn("MAT-001", response["answer"])

    def test_inbound_intent_calls_inbound_tool(self) -> None:
        response, tool = self._run_with_tool(
            "MAT-001 有多少在途？",
            tool_result(data={"ordered_qty": "10", "received_qty": None, "in_transit_qty": None}),
        )
        self.assertEqual(response["query_type"], "inbound")
        self.assertEqual(tool.calls[0]["material_code"], "MAT-001")
        self.assertIn("在途数量 未知", response["answer"])
        self.assertNotIn("在途数量 0", response["answer"])

    def test_unknown_quantities_are_not_converted_to_zero(self) -> None:
        response, _ = self._run_with_tool(
            "查询 MAT-001 库存",
            tool_result(data={"on_hand_qty": "8", "available_qty": None, "reserved_qty": None}),
        )
        self.assertIn("可用数量为 未知", response["answer"])
        self.assertIn("预留数量为 未知", response["answer"])
        self.assertIsNone(response["data"]["available_qty"])

    def test_item_not_found_does_not_guess_inventory(self) -> None:
        response, _ = self._run_with_tool("查一下 MAT-999 库存", tool_result("item_not_found"))
        self.assertIn("当前事实库没有对应信息", response["answer"])
        self.assertNotIn("可能还有库存", response["answer"])
        self.assertIsNone(response["data"])

    def test_data_unavailable_does_not_guess_arrival(self) -> None:
        response, _ = self._run_with_tool("MAT-001 什么时候到货？", tool_result("data_unavailable"))
        self.assertEqual(response["query_type"], "inbound")
        self.assertIn("当前事实库没有对应信息", response["answer"])
        self.assertNotIn("预计", response["answer"])

    def test_absent_snapshot_and_bom_refuse_without_guessing(self) -> None:
        for question, expected in [
            ("查询 MAT-001 库存", "没有已发布库存快照"),
            ("查询 PARENT-1 V1 的 BOM", "没有已发布 BOM 事实"),
        ]:
            with self.subTest(question=question):
                response, _ = self._run_with_tool(question, tool_result("data_unavailable"))
            self.assertIn("当前事实库没有对应信息", response["answer"])
            self.assertIn(expected, response["answer"])
            self.assertIsNone(response["data"])

    def test_invalid_query_does_not_invent_missing_bom_version(self) -> None:
        response, tool = self._run_with_tool("查询 PARENT-1 的 BOM", tool_result("invalid_query"))
        self.assertEqual(tool.calls, [{"parent_material_code": "PARENT-1", "revision": ""}])
        self.assertIn("当前事实库没有对应信息", response["answer"])

    def test_llm_cannot_insert_material_not_in_user_request(self) -> None:
        with patch("agents.fact_query_agent.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "agents.fact_query_agent._invoke_structured_llm",
            return_value=FactQueryIntent(query_type="inventory", material_code="MAT-999"),
        ):
            response, tool = self._run_with_tool(
                "查一下 MAT-001 库存",
                tool_result(data={"on_hand_qty": "5", "available_qty": None, "reserved_qty": None}),
            )
        self.assertEqual(response["parser_source"], "rule_fallback")
        self.assertEqual(tool.calls[0]["material_code"], "MAT-001")

    def test_llm_success_only_routes_tool_and_does_not_supply_answer_facts(self) -> None:
        with patch("agents.fact_query_agent.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "agents.fact_query_agent._invoke_structured_llm",
            return_value=FactQueryIntent(query_type="inventory", material_code="MAT-001"),
        ):
            response, tool = self._run_with_tool(
                "查一下 MAT-001 库存",
                tool_result(data={"on_hand_qty": "6", "available_qty": None, "reserved_qty": None}),
            )
        self.assertEqual(response["parser_source"], "llm")
        self.assertEqual(tool.calls[0]["material_code"], "MAT-001")
        self.assertIn("在库数量为 6", response["answer"])
        self.assertIn("可用数量为 未知", response["answer"])

    def test_literal_material_code_wins_over_llm_truncation(self) -> None:
        with patch("agents.fact_query_agent.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "agents.fact_query_agent._invoke_structured_llm",
            return_value=FactQueryIntent(query_type="inventory", material_code="MAT"),
        ):
            _, tool = self._run_with_tool("查询 MAT-001 库存", tool_result("data_unavailable"))
        self.assertEqual(tool.calls[0]["material_code"], "MAT-001")

    def test_llm_failure_falls_back_to_rule_route(self) -> None:
        with patch("agents.fact_query_agent.get_llm_configuration_status", return_value={"status": "ok"}), patch(
            "agents.fact_query_agent._invoke_structured_llm", side_effect=TimeoutError("secret internal error")
        ):
            response, tool = self._run_with_tool("查询 MAT-001 库存", tool_result("data_unavailable"))
        self.assertEqual(response["parser_source"], "rule_fallback")
        self.assertEqual(len(tool.calls), 1)
        self.assertNotIn("secret", response["answer"])

    def test_unrecognized_request_does_not_call_any_tool(self) -> None:
        with patch("agents.fact_query_agent.get_fact_query_tool") as lookup:
            response = run_fact_query_agent("你好")
        lookup.assert_not_called()
        self.assertEqual(response["status"], "invalid_query")
        self.assertIn("当前事实库没有对应信息", response["answer"])

    def test_malformed_tool_result_fails_closed(self) -> None:
        response, _ = self._run_with_tool("查 MAT-001 库存", {"status": "ok", "data": {"on_hand_qty": "99"}})
        self.assertEqual(response["status"], "query_failed")
        self.assertIsNone(response["data"])
        self.assertNotIn("99", response["answer"])


if __name__ == "__main__":
    unittest.main()
