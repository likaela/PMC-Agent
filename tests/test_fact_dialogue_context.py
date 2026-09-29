"""统一入口中的事实追问、来源引用与 PMC 会话隔离。"""

from __future__ import annotations

import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from services.fact_dialogue_context_service import (
    get_fact_dialogue_context,
    remember_fact_dialogue_context,
)


def _fact_result(
    kind: str,
    code: str,
    *,
    status: str = "ok",
    revision: str | None = None,
) -> dict:
    query = {"parent_material_code" if kind == "bom" else "material_code": code}
    if revision:
        query["revision"] = revision
    data = (
        {"revision": revision, "lines": [], "line_count": 0}
        if kind == "bom" else
        {"on_hand_qty": "7", "available_qty": None, "reserved_qty": None}
    ) if status == "ok" else None
    return {
        "status": status,
        "query": query,
        "data": data,
        "completeness": {"on_hand_qty": True, "available_qty": False} if status == "ok" else {},
        "provenance": {
            "source_file": "published.xlsx",
            "import_batch_id": "batch-test",
            "snapshot_at": "2026-09-20T00:00:00+00:00",
            "bom_version": revision,
        } if status == "ok" else None,
        "warnings": [],
        "query_type": kind,
        "tool_name": "controlled_fact_tool",
        "parser_source": "rule_fallback",
        "answer": "当前事实库没有对应信息。" if status != "ok" else "仅依据已发布事实作答。",
    }


class FactDialogueContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.llm = patch(
            "services.agent_intent_router.get_llm_configuration_status",
            return_value={"status": "warning"},
        )
        self.llm.start()
        self.addCleanup(self.llm.stop)
        self.fact_llm = patch(
            "agents.fact_query_agent.get_llm_configuration_status",
            return_value={"status": "warning"},
        )
        self.fact_llm.start()
        self.addCleanup(self.fact_llm.stop)

    def test_multiturn_inventory_inherits_only_fact_material(self) -> None:
        from tests.test_fact_query_agent import FakeTool, tool_result

        fake = FakeTool("inventory_fact", tool_result(data={
            "on_hand_qty": "7", "available_qty": None, "reserved_qty": None,
        }))
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake), patch(
            "api.routes.agent.chat"
        ) as pmc_chat:
            first = self.client.post("/api/v1/agent/query", json={"message": "查询 MAT-001 库存"}).json()
            session_id = first["structured_data"]["fact_session_id"]
            second = self.client.post("/api/v1/agent/query", json={
                "message": "还能用吗？", "fact_session_id": session_id,
                "active_context": "fact_query",
            }).json()
        self.assertEqual(second["intent"], "fact_query")
        self.assertEqual(fake.calls[1]["material_code"], "MAT-001")
        self.assertEqual(second["structured_data"]["fact_session_id"], session_id)
        self.assertIn("不能仅凭在库数量判断是否可用", second["answer"])
        self.assertIsNone(second["structured_data"]["data"]["available_qty"])
        pmc_chat.assert_not_called()

    def test_explicit_new_material_does_not_inherit_old_time(self) -> None:
        session_id = remember_fact_dialogue_context(
            None, material_code="MAT-001", query_type="inventory",
            as_of="2026-09-20T00:00:00+00:00",
        )
        from tests.test_fact_query_agent import FakeTool, tool_result

        result = tool_result("data_unavailable")
        result["query"] = {"material_code": "MAT-002"}
        fake = FakeTool("inventory_fact", result)
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake):
            response = self.client.post("/api/v1/agent/query", json={
                "message": "查询 MAT-002 库存", "fact_session_id": session_id,
                "active_context": "fact_query",
            }).json()
        self.assertEqual(fake.calls[0], {"material_code": "MAT-002", "as_of": None})
        self.assertEqual(get_fact_dialogue_context(session_id).material_code, "MAT-002")
        self.assertEqual(response["status"], "data_unavailable")

    def test_bom_parent_and_version_are_kept_for_followup(self) -> None:
        from tests.test_fact_query_agent import FakeTool, tool_result

        result = tool_result(data={"revision": "V1", "lines": []})
        result["query"] = {"parent_material_code": "PARENT-1", "revision": "V1"}
        result["provenance"]["bom_version"] = "V1"
        fake = FakeTool("bom_fact", result)
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake):
            first = self.client.post("/api/v1/agent/query", json={"message": "查询 PARENT-1 V1 的 BOM"}).json()
            second = self.client.post("/api/v1/agent/query", json={
                "message": "这个版本的明细呢？",
                "fact_session_id": first["structured_data"]["fact_session_id"],
                "active_context": "fact_query",
            }).json()
        self.assertEqual(fake.calls[-1], {"parent_material_code": "PARENT-1", "revision": "V1"})
        self.assertEqual(second["provenance"]["bom_version"], "V1")

    def test_query_type_can_change_without_changing_material(self) -> None:
        from tests.test_fact_query_agent import FakeTool, tool_result

        session_id = remember_fact_dialogue_context(
            None, material_code="MAT-001", query_type="inventory",
        )
        fake = FakeTool("inventory_batches_fact", tool_result(data={"batches": []}))
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake):
            response = self.client.post("/api/v1/agent/query", json={
                "message": "这个物料有哪些批次？", "fact_session_id": session_id,
                "active_context": "fact_query",
            }).json()
        self.assertEqual(response["structured_data"]["query_type"], "inventory_batches")
        self.assertEqual(fake.calls[0]["material_code"], "MAT-001")
        self.assertEqual(get_fact_dialogue_context(session_id).query_type, "inventory_batches")

    def test_fact_query_does_not_enter_pmc_even_with_workflow_id(self) -> None:
        with patch("api.routes.agent.chat") as pmc_chat, patch(
            "api.routes.agent.run_fact_query_agent",
            return_value=_fact_result("inventory", "MAT-001"),
        ):
            response = self.client.post("/api/v1/agent/query", json={
                "message": "查询 MAT-001 库存", "workflow_id": "existing-pmc-workflow",
                "active_context": "pmc_analysis",
            }).json()
        self.assertEqual(response["intent"], "fact_query")
        pmc_chat.assert_not_called()

    def test_explicit_fact_query_can_resume_after_pmc_view(self) -> None:
        from tests.test_fact_query_agent import FakeTool, tool_result

        session_id = remember_fact_dialogue_context(
            None, material_code="MAT-001", query_type="inventory",
        )
        fake = FakeTool("inventory_fact", tool_result(data={"on_hand_qty": "7", "available_qty": None}))
        with patch("agents.fact_query_agent.get_fact_query_tool", return_value=fake), patch(
            "api.routes.agent.chat"
        ) as pmc_chat:
            response = self.client.post("/api/v1/agent/query", json={
                "message": "该物料库存还有多少？", "workflow_id": "existing-pmc-workflow",
                "fact_session_id": session_id, "active_context": "pmc_analysis",
            }).json()
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(fake.calls[0]["material_code"], "MAT-001")
        pmc_chat.assert_not_called()

    def test_pmc_context_survives_interleaved_fact_query(self) -> None:
        with patch.dict(os.environ, {"PMC_DATA_SOURCE": "demo"}):
            first = self.client.post("/api/v1/agent/query", json={
                "message": "我要生产100台KQ-Z112",
            }).json()
            workflow_id = first["structured_data"]["conversation_workflow_id"]
            with patch("api.routes.agent.run_fact_query_agent", return_value=_fact_result(
                "inventory", "MAT-001",
            )):
                fact = self.client.post("/api/v1/agent/query", json={
                    "message": "查询 MAT-001 库存", "workflow_id": workflow_id,
                    "active_context": "pmc_analysis",
                }).json()
            resumed = self.client.post("/api/v1/agent/query", json={
                "message": "为什么不能生产？", "workflow_id": workflow_id,
                "fact_session_id": fact["structured_data"]["fact_session_id"],
                "active_context": "fact_query",
            }).json()
        self.assertEqual(fact["intent"], "fact_query")
        self.assertEqual(resumed["intent"], "pmc_analysis")
        self.assertEqual(resumed["structured_data"]["turn_type"], "explanation")
        self.assertEqual(resumed["structured_data"]["conversation_workflow_id"], workflow_id)

    def test_unknown_fact_session_never_guesses_material(self) -> None:
        with patch("api.routes.agent.run_fact_query_agent") as fact_agent, patch(
            "api.routes.agent.chat"
        ) as pmc_chat:
            response = self.client.post("/api/v1/agent/query", json={
                "message": "还能用吗？", "fact_session_id": "expired-session",
                "active_context": "fact_query",
            }).json()
        self.assertEqual(response["intent"], "clarification")
        fact_agent.assert_not_called()
        pmc_chat.assert_not_called()

    def test_no_fact_cases_explicitly_refuse(self) -> None:
        for status, kind in [
            ("item_not_found", "inventory"),
            ("data_unavailable", "inventory"),
            ("data_unavailable", "inbound"),
            ("data_unavailable", "bom"),
        ]:
            with self.subTest(status=status, kind=kind), patch(
                "api.routes.agent.run_fact_query_agent",
                return_value=_fact_result(kind, "MAT-001", status=status, revision="V1"),
            ):
                message = {
                    "inventory": "查询 MAT-001 库存",
                    "inbound": "查询 MAT-001 在途",
                    "bom": "查询 MAT-001 V1 的 BOM",
                }[kind]
                response = self.client.post("/api/v1/agent/query", json={"message": message}).json()
            self.assertIn("当前事实库没有对应信息", response["answer"])
            self.assertIsNone(response["structured_data"]["data"])
            self.assertIsNone(response["provenance"])


if __name__ == "__main__":
    unittest.main()
