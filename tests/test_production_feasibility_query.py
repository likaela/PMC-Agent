"""已发布事实组合的理论产能，不复用 Demo 或 PMC 生产决策算法。"""

from __future__ import annotations

import os
import inspect
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from agents.production_feasibility_agent import run_production_feasibility_agent
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore
from services.bom_import_service import BomImportService
from services.inventory_import_service import InventoryImportService
from services.production_feasibility_query_service import ProductionFeasibilityQueryService
from tests.test_fact_query_tools import _create_bom_workbook
from tests.test_inventory_fact_import import _create_inventory_workbook, _seed_item
from tools.agent_tools import ALL_AGENT_TOOLS
from tools.fact_query_tools import FACT_QUERY_TOOLS
from tools.production_feasibility_query_tool import published_production_capacity_query


def _bom(lines: list[tuple[str, str, str]], *, unit: str = "件") -> dict:
    return {
        "status": "ok", "query": {"parent_material_code": "PARENT-1", "revision": "V1"},
        "data": {
            "parent_item": {"material_code": "PARENT-1", "unit": unit},
            "revision": "V1",
            "lines": [
                {
                    "child_item": {"material_code": code}, "qty_per": qty,
                    "unit": line_unit,
                    "provenance": {"source_file": "bom.xlsx", "import_batch_id": "bom-batch", "sheet_name": "明细", "row_number": index},
                }
                for index, (code, qty, line_unit) in enumerate(lines, 5)
            ],
        },
        "completeness": {"bom_lines": True, "qty_per": True},
        "provenance": {"source_file": "bom.xlsx", "import_batch_id": "bom-batch", "bom_version": "V1", "sheet_name": "明细"},
        "warnings": [],
    }


def _inventory(code: str, available: str | None, *, batch: str = "stock-batch", snapshot: str = "2026-09-20T00:00:00+00:00", unit: str = "件") -> dict:
    return {
        "status": "ok", "query": {"material_code": code},
        "data": {"canonical_item": {"material_code": code, "unit": unit}, "on_hand_qty": "999", "available_qty": available},
        "completeness": {"available_qty": available is not None, "duplicate_free": True},
        "provenance": {"source_file": "stock.xlsx", "import_batch_id": batch, "snapshot_at": snapshot},
        "warnings": [],
    }


class FakeFacts:
    def __init__(self, bom: dict, inventories: dict[str, dict], inbound: dict[str, dict] | None = None) -> None:
        self.bom = bom
        self.inventories = inventories
        self.inbound = inbound or {}
        self.calls: list[tuple] = []

    def query_bom(self, product: str, version: str) -> dict:
        self.calls.append(("bom", product, version))
        return self.bom

    def query_inventory(self, code: str, as_of: str) -> dict:
        self.calls.append(("inventory", code, as_of))
        return self.inventories.get(code, {"status": "data_unavailable", "data": None})

    def query_inbound(self, code: str, as_of: str) -> dict:
        self.calls.append(("inbound", code, as_of))
        return self.inbound.get(code, {"status": "data_unavailable", "data": None})


class ProductionFeasibilityQueryTests(unittest.TestCase):
    def test_new_tool_is_independent_of_demo_tools_and_raw_excel(self) -> None:
        existing = {tool.name for tool in [*ALL_AGENT_TOOLS, *FACT_QUERY_TOOLS]}
        self.assertNotIn(published_production_capacity_query.name, existing)
        source = inspect.getsource(ProductionFeasibilityQueryService).lower()
        self.assertNotIn("load_workbook", source)
        self.assertNotIn("data/raw", source)
        self.assertNotIn("mrp_service", source)
        self.assertNotIn("production_service", source)

    def test_capacity_shortage_limiters_and_provenance_are_deterministic(self) -> None:
        facts = FakeFacts(
            _bom([("MAT-A", "2", "件"), ("MAT-B", "3", "件"), ("MAT-A", "1", "件")]),
            {"MAT-A": _inventory("MAT-A", "150"), "MAT-B": _inventory("MAT-B", "210")},
            {"MAT-A": {
                "status": "ok", "data": {"in_transit_qty": "1000"},
                "completeness": {"in_transit_qty": True},
                "provenance": {"source_file": "po.xlsx", "import_batch_id": "po-batch", "observed_at": "2026-09-20T00:00:00+00:00"},
            }},
        )
        result = ProductionFeasibilityQueryService(facts).query(
            "PARENT-1", "V1", requested_quantity=100, requested_unit="件",
            as_of="2026-09-21T00:00:00+00:00",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["max_producible_quantity"], 50)
        self.assertFalse(result["data"]["inventory_sufficient_for_requested"])
        self.assertEqual([row["material_code"] for row in result["data"]["limiting_materials"]], ["MAT-A"])
        self.assertEqual(result["data"]["materials"][0]["qty_per"], "3")
        self.assertEqual(result["data"]["materials"][0]["shortage_qty"], "150")
        self.assertEqual(result["data"]["materials"][0]["inbound_qty"], "1000")
        self.assertEqual(result["provenance"]["bom"]["source_file"], "bom.xlsx")
        self.assertEqual(result["provenance"]["inventory"][0]["import_batch_id"], "stock-batch")
        self.assertNotIn("source_file_id", result["provenance"]["bom"])

    def test_decimal_usage_uses_exact_floor_without_float_rounding(self) -> None:
        facts = FakeFacts(_bom([("MAT-A", "0.5", "件")]), {"MAT-A": _inventory("MAT-A", "1.25")})
        result = ProductionFeasibilityQueryService(facts).query(
            "PARENT-1", "V1", requested_quantity=3,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["max_producible_quantity"], 2)
        self.assertEqual(result["data"]["materials"][0]["shortage_qty"], "0.25")

    def test_missing_bom_refuses_capacity(self) -> None:
        facts = FakeFacts({"status": "data_unavailable", "data": None}, {})
        result = ProductionFeasibilityQueryService(facts).query("PARENT-1", "V1")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"])
        self.assertEqual(facts.calls, [("bom", "PARENT-1", "V1")])

    def test_unknown_available_cannot_use_on_hand_as_capacity(self) -> None:
        facts = FakeFacts(_bom([("MAT-A", "2", "件")]), {"MAT-A": _inventory("MAT-A", None)})
        result = ProductionFeasibilityQueryService(facts).query("PARENT-1", "V1", requested_quantity=20)
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"]["max_producible_quantity"])
        self.assertIsNone(result["data"]["materials"][0]["shortage_qty"])
        self.assertIn("MAT-A", result["data"]["unavailable_materials"])

    def test_known_bom_requirements_are_visible_even_when_capacity_unknown(self) -> None:
        facts = FakeFacts(_bom([("MAT-A", "2", "件")]), {"MAT-A": _inventory("MAT-A", None)})
        with patch("agents.production_feasibility_agent.published_production_capacity_query") as tool:
            tool.invoke.side_effect = lambda arguments: ProductionFeasibilityQueryService(facts).query(
                arguments["product"], arguments["bom_version"],
                requested_quantity=arguments["requested_quantity"],
                requested_unit=arguments["requested_unit"],
            )
            result = run_production_feasibility_agent("PARENT-1 V1 100件需要哪些物料？")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIn("MAT-A 200 件", result["answer"])
        self.assertIn("无法确定最多可生产多少", result["answer"])

    def test_parent_unit_mismatch_refuses_unverified_conversion(self) -> None:
        facts = FakeFacts(_bom([("MAT-A", "2", "件")], unit="件"), {"MAT-A": _inventory("MAT-A", "100")})
        result = ProductionFeasibilityQueryService(facts).query(
            "PARENT-1", "V1", requested_quantity=10, requested_unit="台",
        )
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"])

    def test_missing_stock_and_unit_mismatch_refuse_capacity(self) -> None:
        missing = FakeFacts(_bom([("MAT-A", "2", "件")]), {})
        self.assertEqual(ProductionFeasibilityQueryService(missing).query("PARENT-1", "V1")["status"], "data_unavailable")
        mismatch = FakeFacts(_bom([("MAT-A", "2", "件")]), {"MAT-A": _inventory("MAT-A", "50", unit="箱")})
        result = ProductionFeasibilityQueryService(mismatch).query("PARENT-1", "V1")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertFalse(result["completeness"]["units"])

    def test_inconsistent_stock_snapshot_refuses_capacity(self) -> None:
        facts = FakeFacts(
            _bom([("MAT-A", "1", "件"), ("MAT-B", "1", "件")]),
            {"MAT-A": _inventory("MAT-A", "50"), "MAT-B": _inventory("MAT-B", "50", batch="other-batch")},
        )
        result = ProductionFeasibilityQueryService(facts).query("PARENT-1", "V1")
        self.assertEqual(result["status"], "data_unavailable")
        self.assertFalse(result["completeness"]["snapshot_coherent"])
        self.assertIsNone(result["data"]["max_producible_quantity"])

    def test_imported_main_inventory_does_not_fabricate_available_qty(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            repository = FactRepository(SQLiteFactStore(directory / "facts.db"))
            repository.migrate()
            _seed_item(repository, "PARENT-1")
            _seed_item(repository, "MAT-001")
            bom = BomImportService(repository).stage_bom(_create_bom_workbook(directory / "bom.xlsx"))
            BomImportService(repository).publish(bom.import_batch_id)
            inventory_path = _create_inventory_workbook(directory / "stock.xlsx", [["S1", "L1", "MAT-001", "B1", 200]])
            stock = InventoryImportService(repository).stage_inventory(inventory_path, snapshot_at=datetime(2026, 9, 20, tzinfo=UTC))
            InventoryImportService(repository).publish(stock.import_batch_id)
            with patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{(directory / 'facts.db').as_posix()}"}):
                response = TestClient(app).post("/api/v1/agent/query", json={
                    "message": "PARENT-1 V1 最多能生产多少件？",
                })
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["intent"], "production_capacity")
            self.assertEqual(payload["status"], "data_unavailable")
            self.assertIsNone(payload["structured_data"]["data"]["max_producible_quantity"])
            self.assertEqual(payload["provenance"]["bom"]["source_file"], "bom.xlsx")

    def test_agent_uses_existing_task_context_without_restarting_workflow(self) -> None:
        class FakeTool:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def invoke(self, arguments: dict) -> dict:
                self.calls.append(arguments)
                return {
                    "status": "ok", "query": arguments,
                    "data": {
                        "max_producible_quantity": 50, "product_unit": "件",
                        "requested_quantity": 100, "inventory_sufficient_for_requested": False,
                        "materials": [{"material_code": "MAT-A", "shortage_qty": "50", "is_short": True}],
                        "limiting_materials": [{"material_code": "MAT-A"}],
                    },
                    "completeness": {"bom": True, "inventory": True, "units": True},
                    "provenance": {"bom": {"source_file": "bom.xlsx"}}, "warnings": [],
                }

        fake = FakeTool()
        with patch("agents.production_feasibility_agent.published_production_capacity_query", fake):
            result = run_production_feasibility_agent(
                "现在库存够吗？",
                task_context={"product": "PARENT-1", "bom_version": "V1", "quantity": 100},
            )
        self.assertEqual(fake.calls[0]["product"], "PARENT-1")
        self.assertEqual(fake.calls[0]["bom_version"], "V1")
        self.assertEqual(fake.calls[0]["requested_quantity"], 100)
        self.assertIn("理论最多可生产 50 件", result["answer"])
        self.assertIn("MAT-A 缺口 50", result["answer"])

    def test_agent_without_product_or_version_does_not_call_tool(self) -> None:
        with patch("agents.production_feasibility_agent.published_production_capacity_query") as tool:
            result = run_production_feasibility_agent("最多能生产多少台？")
        self.assertEqual(result["status"], "invalid_query")
        self.assertIsNone(result["data"])
        tool.invoke.assert_not_called()

    def test_api_reuses_read_only_pmc_task_context(self) -> None:
        with patch("services.agent_intent_router.get_llm_configuration_status", return_value={"status": "warning"}), patch(
            "api.routes.agent.get_pmc_workflow_state",
            return_value={"product": "PARENT-1", "bom_version": "V1", "quantity": 100},
        ), patch("api.routes.agent.run_production_feasibility_agent", return_value={
            "status": "data_unavailable", "query": {"product": "PARENT-1", "bom_version": "V1"},
            "data": None, "completeness": {}, "provenance": None, "warnings": [],
            "answer": "当前事实库数据不足。",
        }) as agent, patch("api.routes.agent.chat") as pmc_chat:
            response = TestClient(app).post("/api/v1/agent/query", json={
                "message": "现在库存够吗？", "workflow_id": "workflow-existing",
                "active_context": "pmc_analysis",
            })
        self.assertEqual(response.json()["intent"], "production_capacity")
        self.assertEqual(agent.call_args.kwargs["task_context"], {
            "product": "PARENT-1", "bom_version": "V1", "quantity": 100,
        })
        pmc_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
