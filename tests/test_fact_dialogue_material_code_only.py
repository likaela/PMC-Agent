"""v1.9.9：单独料号与口语库存数量问法必须进入精确事实查询。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agents.fact_query_agent import FactQueryIntent
from api.app import app
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.agent_intent_router import IntentExtraction
from services.inventory_import_service import InventoryImportService
from tests.test_inventory_fact_import import _create_inventory_workbook, _seed_item


class MaterialCodeOnlyDialogueTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        database = directory / "facts.db"
        repository = FactRepository(SQLiteFactStore(database))
        repository.migrate()
        for code in ("1305000050101", "MAT-001", "KQ-Z112"):
            _seed_item(repository, code)
        importer = InventoryImportService(repository)
        importer.inventory_repository.add_item_alias("MAT-001", "ALIAS-001")
        workbook = _create_inventory_workbook(
            directory / "stock-fixture.xlsx",
            [
                ["S1", "L1", "1305000050101", "B1", 7],
                ["S1", "L2", "MAT-001", "B2", 5],
            ],
        )
        staged = importer.stage_inventory(workbook, snapshot_at=datetime(2026, 9, 20, tzinfo=UTC))
        importer.publish(staged.import_batch_id)
        environment = patch.dict(os.environ, {
            "PMC_FACT_DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "PMC_DATA_SOURCE": "demo",
        })
        environment.start()
        self.addCleanup(environment.stop)
        for target in (
            "services.agent_intent_router.get_llm_configuration_status",
            "agents.fact_query_agent.get_llm_configuration_status",
        ):
            disabled = patch(target, return_value={"status": "warning"})
            disabled.start()
            self.addCleanup(disabled.stop)
        self.client = TestClient(app)

    def query(self, message: str, **context: str) -> dict:
        response = self.client.post("/api/v1/agent/query", json={"message": message, **context})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_numeric_code_only_defaults_to_inventory(self) -> None:
        response = self.query("1305000050101")
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["structured_data"]["query_type"], "inventory")
        self.assertEqual(response["structured_data"]["query"]["material_code"], "1305000050101")
        self.assertEqual(response["structured_data"]["query"]["resolved_by"], "canonical_item")
        self.assertEqual(response["structured_data"]["data"]["on_hand_qty"], "7")
        self.assertIsNone(response["structured_data"]["data"]["available_qty"])

    def test_numeric_code_with_colloquial_quantity(self) -> None:
        for message in (
            "1305000050101还有几件",
            "1305000050101剩多少",
            "1305000050101剩余多少",
            "1305000050101余多少",
            "1305000050101数量多少",
            "1305000050101几个",
            "1305000050101几件",
        ):
            with self.subTest(message=message):
                response = self.query(message)
                self.assertEqual(response["intent"], "fact_query")
                self.assertEqual(response["structured_data"]["query_type"], "inventory")
                self.assertEqual(response["structured_data"]["query"]["material_code"], "1305000050101")
                self.assertEqual(response["structured_data"]["data"]["on_hand_qty"], "7")

    def test_inventory_query_without_separator(self) -> None:
        response = self.query("查询库存1305000050101")
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(response["structured_data"]["query"]["material_code"], "1305000050101")

    def test_standard_code_and_alias_only(self) -> None:
        for message, requested, resolved_by in (
            ("MAT-001库存", "MAT-001", "canonical_item"),
            ("MAT-001", "MAT-001", "canonical_item"),
            ("ALIAS-001", "ALIAS-001", "item_alias"),
        ):
            with self.subTest(message=message):
                response = self.query(message)
                self.assertEqual(response["intent"], "fact_query")
                self.assertEqual(response["structured_data"]["query"]["material_code"], requested)
                self.assertEqual(response["structured_data"]["query"]["resolved_by"], resolved_by)
                self.assertEqual(response["structured_data"]["query"]["resolved_material_code"], "MAT-001")

    def test_product_code_with_quantity_phrase_does_not_invent_stock(self) -> None:
        response = self.query("KQ-Z112还有多少")
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(response["structured_data"]["query"]["material_code"], "KQ-Z112")
        self.assertEqual(response["status"], "data_unavailable")
        self.assertNotIn("on_hand_qty", response["structured_data"]["data"] or {})
        self.assertNotIn("在库数量为 0", response["answer"])

    def test_unknown_code_is_item_not_found_not_clarification(self) -> None:
        response = self.query("1305000050199")
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(response["status"], "item_not_found")
        self.assertEqual(response["structured_data"]["query"]["material_code"], "1305000050199")
        self.assertIn("未找到物料编码 1305000050199", response["answer"])
        self.assertIsNone(response["structured_data"]["data"])

    def test_code_only_switches_away_from_previous_fact_material(self) -> None:
        first = self.query("MAT-001库存")
        second = self.query(
            "1305000050101",
            fact_session_id=first["structured_data"]["fact_session_id"],
            active_context="fact_query",
        )
        self.assertEqual(second["intent"], "fact_query")
        self.assertEqual(second["structured_data"]["query"]["resolved_material_code"], "1305000050101")
        self.assertEqual(second["structured_data"]["data"]["on_hand_qty"], "7")

    def test_rule_and_literal_code_override_llm_guess(self) -> None:
        with patch(
            "services.agent_intent_router.get_llm_configuration_status",
            return_value={"status": "ok"},
        ), patch(
            "services.agent_intent_router._invoke_llm_classification",
            return_value=IntentExtraction(intent="pmc_analysis"),
        ), patch(
            "agents.fact_query_agent.get_llm_configuration_status",
            return_value={"status": "ok"},
        ), patch(
            "agents.fact_query_agent._invoke_structured_llm",
            return_value=FactQueryIntent(query_type="inventory", material_code="1305000050199"),
        ):
            response = self.query("1305000050101")
        self.assertEqual(response["intent"], "fact_query")
        self.assertEqual(response["structured_data"]["query"]["material_code"], "1305000050101")
        self.assertEqual(response["structured_data"]["data"]["on_hand_qty"], "7")

    def test_short_number_is_not_assumed_to_be_material(self) -> None:
        response = self.query("100")
        self.assertEqual(response["intent"], "clarification")

    def test_explicit_production_request_still_uses_pmc(self) -> None:
        response = self.query("我要生产100台KQ-Z112")
        self.assertEqual(response["intent"], "pmc_analysis")


if __name__ == "__main__":
    unittest.main()
