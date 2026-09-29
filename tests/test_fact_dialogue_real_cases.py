"""v1.9.9 自然语言事实查询：精确身份、连续上下文与拒答。"""

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
from services.inventory_import_service import InventoryImportService
from tests.test_inventory_fact_import import _create_inventory_workbook, _seed_item


class FactDialogueRealCasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.database = self.path / "facts.db"
        repository = FactRepository(SQLiteFactStore(self.database))
        repository.migrate()
        for code in ("1305000050101", "MAT-001", "KQ-Z112", "NO-STOCK"):
            _seed_item(repository, code)
        importer = InventoryImportService(repository)
        importer.inventory_repository.add_item_alias("MAT-001", "ALIAS-001")
        importer.inventory_repository.add_item_alias("MAT-001", "旧料号甲")
        source = _create_inventory_workbook(
            self.path / "published-stock.xlsx",
            [
                ["S1", "L1", "1305000050101", "B1", 7],
                ["S1", "L2", "1305000050101", "B2", 3],
                ["S1", "L3", "MAT-001", "B3", 5],
            ],
        )
        staged = importer.stage_inventory(source, snapshot_at=datetime(2026, 9, 20, tzinfo=UTC))
        importer.publish(staged.import_batch_id)
        self.batch_id = staged.import_batch_id
        self.client = TestClient(app)
        self.environment = patch.dict(os.environ, {
            "PMC_FACT_DATABASE_URL": f"sqlite:///{self.database.as_posix()}",
            "PMC_DATA_SOURCE": "demo",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for target in (
            "services.agent_intent_router.get_llm_configuration_status",
            "agents.fact_query_agent.get_llm_configuration_status",
        ):
            disabled = patch(target, return_value={"status": "warning"})
            disabled.start()
            self.addCleanup(disabled.stop)

    def query(self, message: str, **context: str) -> dict:
        response = self.client.post("/api/v1/agent/query", json={"message": message, **context})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_numeric_material_and_exact_resolver(self) -> None:
        result = self.query("查询物料库存，1305000050101还有多少")
        self.assertEqual(result["intent"], "fact_query")
        self.assertEqual(result["structured_data"]["query_type"], "inventory")
        self.assertEqual(result["structured_data"]["query"]["resolved_material_code"], "1305000050101")
        self.assertEqual(result["structured_data"]["query"]["resolved_by"], "canonical_item")
        self.assertEqual(result["structured_data"]["data"]["on_hand_qty"], "10")
        self.assertIsNone(result["structured_data"]["data"]["available_qty"])
        self.assertEqual(result["provenance"]["import_batch_id"], self.batch_id)
        self.assertEqual(result["provenance"]["source_file"], "published-stock.xlsx")
        self.assertEqual(result["provenance"]["snapshot_at"], "2026-09-20T00:00:00+00:00")

    def test_mat_code_and_alias_resolve_without_fuzzy_guess(self) -> None:
        canonical = self.query("查询 MAT-001 库存")
        alias = self.query("ALIAS-001还有多少库存？")
        named_alias = self.query("查询“旧料号甲”库存")
        self.assertEqual(canonical["structured_data"]["query"]["resolved_by"], "canonical_item")
        self.assertEqual(alias["structured_data"]["query"]["resolved_by"], "item_alias")
        self.assertEqual(alias["structured_data"]["query"]["resolved_material_code"], "MAT-001")
        self.assertEqual(alias["structured_data"]["data"]["on_hand_qty"], "5")
        self.assertEqual(named_alias["structured_data"]["query"]["resolved_material_code"], "MAT-001")
        self.assertEqual(named_alias["structured_data"]["query"]["resolved_by"], "item_alias")

    def test_product_code_inventory_and_existing_item_without_snapshot(self) -> None:
        for message in ("KQ-Z112库存", "查询 NO-STOCK 库存"):
            with self.subTest(message=message):
                result = self.query(message)
                self.assertEqual(result["intent"], "fact_query")
                self.assertEqual(result["status"], "data_unavailable")
                self.assertIn("已找到该物料", result["answer"])
                self.assertNotIn("在库数量为 0", result["answer"])

    def test_missing_item_is_distinct_from_missing_snapshot(self) -> None:
        result = self.query("查询 MAT-999 库存")
        self.assertEqual(result["status"], "item_not_found")
        self.assertIn("未找到物料编码 MAT-999", result["answer"])
        self.assertIsNone(result["structured_data"]["data"])

    def test_inventory_followups_keep_item_and_explicit_new_code_wins(self) -> None:
        first = self.query("查询 MAT-001 库存")
        context = {"fact_session_id": first["structured_data"]["fact_session_id"], "active_context": "fact_query"}
        followup = self.query("还能用吗？", **context)
        self.assertEqual(followup["structured_data"]["query"]["resolved_material_code"], "MAT-001")
        self.assertIn("不能仅凭在库数量判断是否可用", followup["answer"])
        changed = self.query("查询 1305000050101 库存", **context)
        self.assertEqual(changed["structured_data"]["query"]["resolved_material_code"], "1305000050101")
        next_turn = self.query("还有多少？", **context)
        self.assertEqual(next_turn["structured_data"]["query"]["resolved_material_code"], "1305000050101")

    def test_batch_followup_uses_same_item(self) -> None:
        first = self.query("查询 1305000050101 库存")
        result = self.query("这个物料有哪些批次？", fact_session_id=first["structured_data"]["fact_session_id"], active_context="fact_query")
        self.assertEqual(result["structured_data"]["query_type"], "inventory_batches")
        self.assertEqual(len(result["structured_data"]["data"]["batches"]), 2)

    def test_colloquial_stock_followup_requires_confirmed_context(self) -> None:
        without_context = self.query("这个料有没有库存？")
        self.assertEqual(without_context["intent"], "fact_query")
        self.assertEqual(without_context["status"], "invalid_query")
        first = self.query("查询 MAT-001 库存")
        with_context = self.query(
            "这个料有没有库存？",
            fact_session_id=first["structured_data"]["fact_session_id"],
            active_context="fact_query",
        )
        self.assertEqual(with_context["structured_data"]["query"]["resolved_material_code"], "MAT-001")

    def test_query_keywords_choose_expected_fact_kind_before_llm(self) -> None:
        from agents.fact_query_agent import _rule_intent
        from services.agent_intent_router import route_agent_message

        for message, kind in (
            ("MAT-001余量多少", "inventory"),
            ("MAT-001存量", "inventory"),
            ("MAT-001哪批有效期近", "inventory_batches"),
            ("MAT-001 FIFO", "inventory_batches"),
            ("KQ-Z112物料清单", "bom"),
            ("MAT-001采购订单", "inbound"),
        ):
            with self.subTest(message=message):
                self.assertEqual(route_agent_message(message)["intent"], "fact_query")
                self.assertEqual(_rule_intent(message).query_type, kind)

    def test_inbound_followup_refuses_without_authoritative_fact(self) -> None:
        first = self.query("查询 MAT-001 库存")
        result = self.query("这个物料什么时候到？", fact_session_id=first["structured_data"]["fact_session_id"], active_context="fact_query")
        self.assertEqual(result["structured_data"]["query_type"], "inbound")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIn("权威在途采购事实", result["answer"])
        self.assertNotIn("预计", result["answer"])

    def test_bom_phrase_routes_but_does_not_guess_version(self) -> None:
        result = self.query("KQ-Z112有哪些物料")
        self.assertEqual(result["intent"], "fact_query")
        self.assertEqual(result["structured_data"]["query_type"], "bom")
        self.assertEqual(result["status"], "invalid_query")
        self.assertIn("BOM 版本", result["answer"])

    def test_existing_product_without_bom_is_data_unavailable(self) -> None:
        result = self.query("查询 KQ-Z112 V01 的BOM")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIn("该产品与版本没有已发布 BOM", result["answer"])

    def test_production_capacity_phrase_keeps_separate_route(self) -> None:
        result = self.query("现在最多能生产多少？")
        self.assertEqual(result["intent"], "production_capacity")
        self.assertEqual(result["status"], "invalid_query")

    def test_production_request_still_uses_existing_pmc_workflow(self) -> None:
        result = self.query("我要生产100台KQ-Z112")
        self.assertEqual(result["intent"], "pmc_analysis")
        self.assertEqual(result["structured_data"]["parsed_task"]["quantity"], 100)

    def test_procurement_word_does_not_hijack_explicit_production_task(self) -> None:
        from services.agent_intent_router import route_agent_message

        self.assertEqual(
            route_agent_message("我要生产100台KQ-Z112，请给出采购建议")["intent"],
            "pmc_analysis",
        )

    def test_tool_failure_hides_internal_exception(self) -> None:
        with patch("agents.fact_query_agent.get_fact_query_tool", side_effect=RuntimeError("secret database password")):
            result = self.query("查询 MAT-001 库存")
        self.assertEqual(result["status"], "query_failed")
        self.assertEqual(result["answer"], "系统查询异常，请稍后重试。")
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
