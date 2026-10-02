"""v1.14 完全合成 published 场景，隔离库、Agent/API、来源和原算法一致性。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from repositories.agent_conversation_repository import AgentConversationRepository
from repositories.demo_scenario_repository import SCENARIO_ID, SCENARIO_ROOT, DemoScenarioRepository
from repositories.fact_query_repository import FactQueryRepository
from repositories.fact_repository import FactRepository
from repositories.fact_store import SQLiteFactStore, PROJECT_ROOT
from repositories.published_purchase_repository import PublishedPurchaseRepository
from services.demo_scenario_agent_service import build_demo_scenario_agent
from services.fact_query_service import FactQueryService
from services.published_planning_service import PublishedPlanningService
from services.published_purchase_planning_service import PublishedPurchasePlanningService
from tests.test_inventory_fact_import import _seed_item
from tools.demo_scenario_tools import build_demo_scenario_tools
from tools.agent_tools import ALL_AGENT_TOOLS
from tools.fact_query_tools import FACT_QUERY_TOOLS


class DemoScenarioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.demo_root = self.root / "demo"
        self.demo = DemoScenarioRepository(runtime_root=self.demo_root)
        self.manifest = self.demo.initialize()
        self.agent = build_demo_scenario_agent(runtime_root=self.demo_root)
        self.session = self.agent.repository.create_session()["session_id"]
        self.tools = build_demo_scenario_tools(self.demo)
        self.real_path = self.root / "enterprise.db"
        self.real = FactRepository(SQLiteFactStore(self.real_path))
        self.real.migrate()
        _seed_item(self.real, "REAL-MAT-01")
        self.real_session = AgentConversationRepository(self.real.store).create_session()["session_id"]
        environment = patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{self.real_path.as_posix()}"})
        environment.start()
        self.addCleanup(environment.stop)
        llm = patch("services.persistent_agent_service.get_llm", side_effect=AssertionError("此场景无需外部LLM"))
        llm.start()
        self.addCleanup(llm.stop)

    def _capacity(self, quantity):
        return self.tools["production_capacity"].invoke(dict(product=self.manifest.product,
            bom_version=self.manifest.revision, effective_date=self.manifest.effective_date.isoformat(),
            requested_quantity=quantity, as_of=self.manifest.snapshot_at.isoformat()))

    def _purchase(self, quantity):
        return self.tools["purchase_planning"].invoke(dict(product=self.manifest.product,
            revision=self.manifest.revision, effective_date=self.manifest.effective_date.isoformat(), quantity=quantity,
            start_date=self.manifest.start_date.isoformat(), as_of=self.manifest.snapshot_at.isoformat()))

    def _inventory_rows(self):
        with self.demo.store.transaction() as connection:
            return self.demo.store.execute(connection,
                "SELECT id, item_id, batch_no, location, on_hand_qty, available_qty, reserved_qty FROM inventory_facts ORDER BY id").fetchall()

    def test_50_is_ready_with_both_rates_one(self):
        result = self._capacity(50)
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertTrue(data["inventory_sufficient_for_requested"])
        self.assertEqual(data["theoretical_max_quantity"], 75)
        self.assertEqual(data["material_type_ready_rate"], "1")
        self.assertEqual(data["quantity_fulfillment_rate"], "1")
        self.assertTrue(all(row["shortage_qty"] == "0" for row in data["materials"]))

    def test_100_has_four_exact_shortages(self):
        data = self._capacity(100)["data"]
        self.assertFalse(data["inventory_sufficient_for_requested"])
        self.assertEqual(data["material_type_ready_rate"], "0")
        self.assertEqual(data["quantity_fulfillment_rate"], "0.75")
        self.assertEqual({row["material_code"]: row["shortage_qty"] for row in data["materials"]},
                         {"DEMO-BOARD-01": "25", "DEMO-CHIP-01": "100", "DEMO-MOTOR-01": "50", "DEMO-SCREW-01": "200"})

    def test_every_leaf_meets_50_100_boundary(self):
        from decimal import Decimal
        for row in self._capacity(100)["data"]["materials"]:
            unit, stock = Decimal(row["required_per_product"]), Decimal(row["available_qty"])
            self.assertLessEqual(50 * unit, stock)
            self.assertGreater(100 * unit, stock)

    def test_existing_multilevel_service_is_authoritative(self):
        facts = FactQueryService(FactQueryRepository(self.demo.facts))
        expected = PublishedPlanningService(facts).query(self.manifest.product, self.manifest.revision,
            self.manifest.effective_date.isoformat(), requested_quantity=100, as_of=self.manifest.snapshot_at.isoformat())
        actual = self._capacity(100)
        self.assertEqual(actual["data"], expected["data"])
        self.assertEqual(actual["completeness"], expected["completeness"])
        board = next(row for row in actual["data"]["materials"] if row["material_code"] == "DEMO-BOARD-01")
        self.assertEqual(len(board["bom_paths"][0]), 2)

    def test_agent_uses_facts_not_hardcoded_50_success(self):
        with self.demo.store.transaction(write_lock=True) as connection:
            self.demo.store.execute(connection,
                "UPDATE inventory_facts SET available_qty='0' WHERE item_id=(SELECT id FROM items WHERE material_code='DEMO-BOARD-01')")
        result = self.agent.query(self.session, "生产50台DEMO-PMC-01")
        self.assertFalse(result["structured_data"]["data"]["inventory_sufficient_for_requested"])
        self.assertIn("50 台方案缺料", result["answer"])
        self.assertNotIn("可以生产 50 台", result["answer"])

    def test_multiple_threads_can_initialize_one_cache_without_duplicates(self):
        from concurrent.futures import ThreadPoolExecutor
        root = self.root / "concurrent"
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: DemoScenarioRepository(runtime_root=root).initialize().scenario_id, range(3)))
        self.assertEqual(results, [SCENARIO_ID] * 3)
        repo = DemoScenarioRepository(runtime_root=root)
        with repo.store.transaction() as connection:
            self.assertEqual(repo.store.execute(connection, "SELECT COUNT(*) FROM bom_lines").fetchone()[0], 5)

    def test_inventory_query_keeps_batches_and_locations(self):
        result = self.tools["inventory"].invoke({"material_code": "DEMO-BOARD-01"})
        self.assertEqual(result["data"]["available_qty"], "75")
        lots = self.tools["inventory_batches"].invoke({"material_code": "DEMO-BOARD-01"})["data"]["batches"]
        self.assertEqual(len(lots), 2)
        self.assertEqual({lot["location"] for lot in lots}, {"DEMO-L1", "DEMO-L2"})

    def test_purchase_parameters_moq_and_cost_reuse_existing_service(self):
        expected = PublishedPurchasePlanningService(PublishedPurchaseRepository(self.demo.facts)).query(
            self.manifest.product, self.manifest.revision, self.manifest.effective_date.isoformat(), 100,
            self.manifest.start_date.isoformat(), as_of=self.manifest.snapshot_at.isoformat())
        actual = self._purchase(100)
        self.assertEqual(actual["status"], "ok")
        self.assertEqual(actual["data"], expected["data"])
        rows = {row["material"]: row for row in actual["data"]["recommendations"]}
        self.assertEqual(rows["DEMO-BOARD-01"]["suggested_purchase_qty"], "30")
        from decimal import Decimal
        self.assertEqual(Decimal(actual["data"]["total_purchase_cost"]), Decimal("1560"))
        self.assertEqual(actual["data"]["missing_fields"], {})

    def test_50_does_not_purchase_and_no_recommendation_changes_stock(self):
        before = self._inventory_rows()
        result = self._purchase(50)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(all(row["suggested_purchase_qty"] == "0" for row in result["data"]["recommendations"]))
        self._purchase(100)
        self._capacity(50)
        self.assertEqual(before, self._inventory_rows())
        self.assertFalse(self._capacity(100)["data"]["inventory_sufficient_for_requested"])

    def test_zero_inbound_has_explicit_closed_order_source(self):
        result = self.tools["inbound"].invoke({"material_code": "DEMO-BOARD-01"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["in_transit_qty"], "0")
        self.assertEqual(result["provenance"]["source_file"], "inbound_facts.json")

    def test_provenance_has_scenario_sources_rows_and_hashes(self):
        result = self._capacity(100)
        self.assertEqual(result["provenance"]["scenario_id"], SCENARIO_ID)
        self.assertTrue(result["provenance"]["synthetic"])
        self.assertEqual(result["provenance"]["bom"][0]["bom_version"], "V01")
        for material in result["data"]["materials"]:
            for path in material["bom_paths"]:
                for relation in path:
                    source = relation["provenance"]
                    self.assertEqual(source["source_file"], "bom_facts.json")
                    self.assertEqual(len(source["content_sha256"]), 64)
                    self.assertGreater(source["row_number"], 0)
                    self.assertTrue(source["import_batch_id"])
        with self.demo.store.transaction() as connection:
            files = self.demo.store.execute(connection, "SELECT original_filename, content_sha256, source_uri FROM source_files").fetchall()
        for name, sha, uri in files:
            self.assertEqual(sha, hashlib.sha256((SCENARIO_ROOT / name).read_bytes()).hexdigest())
            self.assertTrue(uri.startswith(f"demo://{SCENARIO_ID}/"))

    def test_idempotent_initialization_does_not_duplicate_facts(self):
        self.demo.initialize()
        self.demo.initialize()
        with self.demo.store.transaction() as connection:
            counts = {table: self.demo.store.execute(connection, f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("items", "bom_headers", "bom_lines", "inventory_facts", "import_batches", "source_files")}
        self.assertEqual(counts, dict(items=6, bom_headers=2, bom_lines=5, inventory_facts=8, import_batches=5, source_files=5))

    def test_changed_package_is_not_silently_republished(self):
        source = self.root / "changed-source"
        shutil.copytree(SCENARIO_ROOT, source, ignore=shutil.ignore_patterns(".runtime"))
        text = (source / "inventory_facts.json").read_text(encoding="utf-8")
        (source / "inventory_facts.json").write_text(text.replace('"40"', '"41"'), encoding="utf-8")
        before = self._inventory_rows()
        with self.assertRaisesRegex(ValueError, "校验值"):
            DemoScenarioRepository(runtime_root=self.demo_root, source_root=source).initialize()
        self.assertEqual(before, self._inventory_rows())

    def test_no_enterprise_store_factory_or_environment_switch(self):
        original = os.environ["PMC_FACT_DATABASE_URL"]
        before = hashlib.sha256(self.real_path.read_bytes()).hexdigest()
        with patch("api.routes.agent.create_fact_store", side_effect=AssertionError("不允许打开企业库")), patch(
            "tools.fact_query_tools.create_fact_store", side_effect=AssertionError("不允许打开企业库")), patch(
            "tools.production_feasibility_query_tool.create_fact_store", side_effect=AssertionError("不允许打开企业库")), patch(
            "tools.published_purchase_tools.create_fact_store", side_effect=AssertionError("不允许打开企业库")):
            self.agent.query(self.session, "生产100台DEMO-PMC-01")
            self.agent.query(self.session, "采购建议")
        self.assertEqual(os.environ["PMC_FACT_DATABASE_URL"], original)
        self.assertEqual(hashlib.sha256(self.real_path.read_bytes()).hexdigest(), before)
        real = FactQueryService(FactQueryRepository(self.real))
        self.assertEqual(real.query_inventory("DEMO-BOARD-01")["status"], "item_not_found")

    def test_private_directories_are_rejected_before_loading(self):
        for private in ("raw", "facts"):
            with self.assertRaises(ValueError):
                DemoScenarioRepository(runtime_root=PROJECT_ROOT / "data" / private / "forbidden-demo")

    def test_existing_foreign_database_is_rejected_without_migration(self):
        target = self.root / "foreign" / "demo_facts.sqlite3"
        foreign = FactRepository(SQLiteFactStore(target))
        foreign.migrate()
        _seed_item(foreign, "REAL-MAT-99")
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "独立数据库"):
            DemoScenarioRepository(runtime_root=target.parent).initialize()
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)

    def test_agent_natural_language_50_then_100_then_reduce(self):
        small = self.agent.query(self.session, "生产50台DEMO-PMC-01")
        large = self.agent.query(self.session, "生产100台DEMO-PMC-01")
        reduced = self.agent.query(self.session, "减少到50台呢？")
        self.assertIn("可以生产 50 台", small["answer"])
        self.assertIn("100 台方案缺料", large["answer"])
        self.assertIn("缺口 25", large["answer"])
        self.assertIn("可以生产 50 台", reduced["answer"])
        self.assertEqual(len(self.agent.repository.history(self.session)["turns"]), 3)

    def test_demo_history_restores_and_cannot_use_enterprise_session(self):
        first = self.agent.query(self.session, "生产100台DEMO-PMC-01")
        fresh = build_demo_scenario_agent(runtime_root=self.demo_root)
        self.assertEqual(fresh.repository.history(self.session)["turns"][0]["response"], first)
        from repositories.agent_conversation_repository import SessionNotFound
        with self.assertRaises(SessionNotFound):
            fresh.query(self.real_session, "生产50台DEMO-PMC-01")
        with self.assertRaises(SessionNotFound):
            AgentConversationRepository(self.real.store).get_session(self.session)

    def test_demo_registry_does_not_pollute_existing_tools(self):
        self.assertTrue({tool.name for tool in self.tools.values()}.isdisjoint({tool.name for tool in FACT_QUERY_TOOLS + ALL_AGENT_TOOLS}))

    def test_api_explicit_scenario_query_history_and_purchase(self):
        client = TestClient(app)
        with patch("services.demo_scenario_agent_service.build_demo_scenario_agent",
                   side_effect=lambda: build_demo_scenario_agent(runtime_root=self.demo_root)):
            first = client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "message": "生产50台DEMO-PMC-01"})
            self.assertEqual(first.status_code, 200)
            sid = first.json()["session_id"]
            second = client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "session_id": sid, "message": "生产100台DEMO-PMC-01"})
            self.assertFalse(second.json()["structured_data"]["data"]["inventory_sufficient_for_requested"])
            purchase = client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "session_id": sid, "message": "采购建议"})
            self.assertEqual(purchase.json()["status"], "ok")
            history = client.get(f"/api/v1/agent/sessions/{sid}", params={"scenario_id": SCENARIO_ID}).json()
            self.assertEqual(history["scenario_id"], SCENARIO_ID)
            self.assertEqual(history["turns"][0]["response"], first.json())
            self.assertEqual(client.get(f"/api/v1/agent/sessions/{sid}").status_code, 404)
            self.assertEqual(client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "session_id": self.real_session, "message": "生产50台DEMO-PMC-01"}).status_code, 404)

    def test_api_session_creation_and_invalid_scenario(self):
        client = TestClient(app)
        with patch("services.demo_scenario_agent_service.build_demo_scenario_agent",
                   side_effect=lambda: build_demo_scenario_agent(runtime_root=self.demo_root)):
            response = client.post("/api/v1/agent/sessions", json={"scenario_id": SCENARIO_ID})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenario_id"], SCENARIO_ID)
        self.assertEqual(client.post("/api/v1/agent/query", json={"scenario_id": "unknown", "message": "生产50台DEMO-PMC-01"}).status_code, 422)
        self.assertEqual(client.post("/api/v1/agent/query", json={"scenario_id": SCENARIO_ID, "workflow_id": "legacy", "message": "生产50台DEMO-PMC-01"}).status_code, 422)

    def test_new_explicit_product_does_not_borrow_demo_metadata(self):
        result = self.agent.query(self.session, "生产50台REAL-PRODUCT-01")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["structured_data"]["query"]["revision"])


if __name__ == "__main__":
    unittest.main()
