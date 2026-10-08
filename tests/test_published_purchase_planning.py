"""v1.12 全部使用合成 published facts，不依赖 raw、LLM 或外部 API。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from repositories.fact_repository import FactRepository
from repositories.fact_store import MIGRATIONS_ROOT, SQLiteFactStore
from repositories.published_purchase_repository import PublishedPurchaseRepository
from services.published_purchase_planning_service import PublishedPurchasePlanningService
from tests.test_inventory_fact_import import _seed_item
from tools.agent_tools import ALL_AGENT_TOOLS
from tools.fact_query_tools import FACT_QUERY_TOOLS
from tools.published_purchase_tools import PUBLISHED_PURCHASE_TOOLS, published_purchase_recommendations_query


AT = "2026-10-01T00:00:00+00:00"
DAY = "2026-10-01"


class PublishedPurchasePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "facts.db"
        self.store = SQLiteFactStore(self.database)
        self.facts = FactRepository(self.store)
        self.facts.migrate()
        self.items = {code: _seed_item(self.facts, code) for code in ("PRODUCT", "MODULE", "MAT-001", "MAT-002")}
        self.repository = PublishedPurchaseRepository(self.facts)
        self.service = PublishedPurchasePlanningService(self.repository)

    def _source(self, name: str, status: str = "published") -> tuple[str, str]:
        batch, source = str(uuid4()), str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO import_batches (id, mapping_name, status, created_at, published_at) VALUES (?, 'v1.12-synthetic', ?, ?, ?)",
                (batch, status, AT, AT))
            self.store.execute(connection,
                "INSERT INTO source_files (id, import_batch_id, original_filename, content_sha256, byte_size, source_kind, source_uri, immutable_copy) "
                "VALUES (?, ?, ?, ?, 1, 'local', ?, ?)",
                (source, batch, name, "c" * 64, f"test://{name}", False))
        return batch, source

    def _bom(self, lines: list[tuple[str, str]], parent: str = "PRODUCT") -> None:
        batch, source = self._source(f"{parent}-bom.xlsx")
        header = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO bom_headers (id, parent_material_code, version, effective_from, import_batch_id, source_file_id, source_sheet) "
                "VALUES (?, ?, 'V1', '2026-09-01', ?, ?, 'BOM')", (header, parent, batch, source))
            for row, (code, quantity) in enumerate(lines, 2):
                self.store.execute(connection,
                    "INSERT INTO bom_lines (id, bom_header_id, item_id, quantity, unit, import_batch_id, source_file_id, source_sheet, source_row_number) "
                    "VALUES (?, ?, ?, ?, '件', ?, ?, 'BOM', ?)", (str(uuid4()), header, self.items[code], quantity, batch, source, row))

    def _inventory(self, quantities: dict[str, str | None], *, expiry: str | None = "2027-01-01", at: str = AT) -> None:
        batch, source = self._source("stock.xlsx")
        snapshot = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inventory_snapshots (id, snapshot_at, observed_at, import_batch_id, source_file_id, source_content_sha256, source_sheet, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '库存', ?)", (snapshot, at, at, batch, source, source, AT))
            for row, (code, quantity) in enumerate(quantities.items(), 2):
                self.store.execute(connection,
                    "INSERT INTO inventory_facts (id, inventory_snapshot_id, item_id, raw_material_code, batch_no, on_hand_qty, available_qty, reserved_qty, "
                    "received_at, expiry_date, import_batch_id, source_file_id, source_sheet, source_row_number) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, '0', '2026-09-01T00:00:00+00:00', ?, ?, ?, '库存', ?)",
                    (str(uuid4()), snapshot, self.items[code], code, f"LOT-{row}", quantity if quantity is not None else "10",
                     quantity, expiry, batch, source, row))

    def _inbound(self, codes: list[str], *, quantity: str = "0", arrival: str = "2026-10-03", at: str = AT) -> None:
        batch, source = self._source("orders.xlsx")
        observation = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inbound_supply_observations (id, observed_at, import_batch_id, source_file_id, source_content_sha256, source_name, published_at) "
                "VALUES (?, ?, ?, ?, ?, '明确采购来源', ?)", (observation, at, batch, source, source, AT))
            for row, code in enumerate(codes, 2):
                ordered = quantity if quantity != "0" else "1"
                received = "0" if quantity != "0" else "1"
                self.store.execute(connection,
                    "INSERT INTO inbound_supply_facts (id, inbound_observation_id, item_id, raw_material_code, ordered_qty, received_qty, in_transit_qty, "
                    "expected_arrival_date, supply_status, import_batch_id, source_file_id, source_sheet, source_row_number) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, '采购', ?)",
                    (str(uuid4()), observation, self.items[code], code, ordered, received, quantity, arrival, batch, source, row))

    def _policy(self, code: str, safety: str | None = "0") -> None:
        batch, source = self._source(f"{code}-safety.xlsx")
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO inventory_risk_policies (id, item_id, safety_stock_qty, unit, effective_from, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "VALUES (?, ?, ?, '件', '2026-09-01', ?, ?, '策略', 2)", (str(uuid4()), self.items[code], safety, batch, source))

    def _price(self, code: str, value: str = "2.50", *, currency: str = "CNY", unit: str | None = "件",
               supplier: str | None = "SUP-1", end: str | None = None, status: str = "published") -> str:
        batch, source = self._source(f"{code}-price.xlsx", status)
        price = str(uuid4())
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO price_records (id, item_id, tax_included_unit_price, currency, unit, supplier_code, effective_from, effective_to, "
                "import_batch_id, source_file_id, source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, '2026-09-01', ?, ?, ?, '价格', 2)",
                (price, self.items[code], value, currency, unit, supplier, end, batch, source))
        return price

    def _parameters(self, code: str, price: str | None, *, moq: str | None = "0", multiple: str | None = "1",
                    packaging: str | None = None, multiple_applicable: bool | None = True,
                    packaging_applicable: bool | None = False, lead: int | None = 3,
                    supplier: str | None = "SUP-1", unit: str | None = "件", status: str = "published",
                    start: str = "2026-09-01", end: str | None = None) -> None:
        batch, source = self._source(f"{code}-parameters.xlsx", status)
        with self.store.transaction() as connection:
            self.store.execute(connection,
                "INSERT INTO purchase_parameter_facts (id, item_id, supplier_code, purchase_unit, minimum_order_quantity, order_multiple, packaging_multiple, "
                "order_multiple_applicable, packaging_multiple_applicable, lead_time_days, price_record_id, effective_from, effective_to, import_batch_id, "
                "source_file_id, source_sheet, source_row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '参数', 2)",
                (str(uuid4()), self.items[code], supplier, unit, moq, multiple, packaging, multiple_applicable,
                 packaging_applicable, lead, price, start, end, batch, source))

    def _prepare(self, *, stock: str | None = "10", safety: str | None = "0", incoming: str = "0",
                 moq: str | None = "0", multiple: str | None = "1", packaging: str | None = None,
                 price: str | None = "2.50", lead: int | None = 3) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": stock})
        self._inbound(["MAT-001"], quantity=incoming)
        self._policy("MAT-001", safety)
        price_id = self._price("MAT-001", price) if price is not None else None
        self._parameters("MAT-001", price_id, moq=moq, multiple=multiple,
                         packaging=packaging, packaging_applicable=packaging is not None, lead=lead)

    def _query(self, quantity: int = 100, **kwargs) -> dict:
        return self.service.query("PRODUCT", "V1", DAY, quantity, "2026-10-20", as_of=AT, **kwargs)

    @staticmethod
    def _line(result: dict) -> dict:
        return result["data"]["recommendations"][0]

    def test_shortage_and_safety_netting_against_stock_and_inbound(self) -> None:
        self._prepare(stock="30", safety="10", incoming="20")
        result = self._query()
        line = self._line(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(line["required_qty"], "100")
        self.assertEqual(line["shortage"], "50")
        self.assertEqual(line["net_purchase_requirement_qty"], "60")
        self.assertEqual(line["suggested_purchase_qty"], "60")
        self.assertEqual(line["supplier"], "SUP-1")

    def test_moq_is_used_when_positive_requirement_is_smaller(self) -> None:
        self._prepare(stock="90", moq="20")
        line = self._line(self._query())
        self.assertEqual(line["shortage"], "10")
        self.assertEqual(line["suggested_purchase_qty"], "20")
        self.assertEqual(line["constraint_extra_qty"], "10")

    def test_120_demand_with_50_packaging_rounds_to_150(self) -> None:
        self._prepare(stock="0", packaging="50")
        line = self._line(self._query(120))
        self.assertEqual(line["suggested_purchase_qty"], "150")
        self.assertEqual(line["effective_order_multiple"], "50")

    def test_both_multiples_use_lcm_instead_of_invalid_sequential_rounding(self) -> None:
        self._prepare(stock="0", multiple="50", packaging="20")
        line = self._line(self._query(120))
        self.assertEqual(line["effective_order_multiple"], "100")
        self.assertEqual(line["suggested_purchase_qty"], "200")

    def test_fractional_constraints_are_exact(self) -> None:
        self._prepare(stock="0.4", moq="0.7", multiple="0.2", packaging="0.3")
        line = self._line(self._query(1))
        self.assertEqual(line["net_purchase_requirement_qty"], "0.6")
        self.assertEqual(line["effective_order_multiple"], "0.6")
        self.assertEqual(line["suggested_purchase_qty"], "1.2")

    def test_no_requirement_does_not_trigger_moq_purchase(self) -> None:
        self._prepare(stock="100", moq="500")
        line = self._line(self._query())
        self.assertEqual(line["suggested_purchase_qty"], "0")
        self.assertEqual(line["risk_level"], "none")

    def test_safety_only_replenishment_is_not_called_production_shortage(self) -> None:
        self._prepare(stock="100", safety="10")
        line = self._line(self._query())
        self.assertEqual(line["shortage"], "0")
        self.assertEqual(line["suggested_purchase_qty"], "10")
        self.assertEqual(line["risk_level"], "buffer_only")

    def test_cost_and_constraint_cost_impact(self) -> None:
        self._prepare(stock="90", moq="20")
        result = self._query()
        line = self._line(result)
        self.assertEqual(line["purchase_cost"], "50.00")
        self.assertEqual(line["unconstrained_cost"], "25.00")
        self.assertEqual(line["constraint_cost_impact"], "25.00")
        self.assertEqual(result["data"]["total_purchase_cost"], "50.00")
        self.assertEqual(result["data"]["total_cost_currency"], "CNY")
        self.assertEqual(result["data"]["total_constraint_cost_impact"], "25.00")

    def test_missing_price_keeps_quantity_but_never_estimates_cost(self) -> None:
        self._prepare(price=None)
        result = self._query()
        line = self._line(result)
        self.assertEqual(line["suggested_purchase_qty"], "90")
        self.assertIsNone(line["purchase_cost"])
        self.assertIsNone(result["data"]["total_purchase_cost"])
        self.assertIn("price_record_id", line["missing_fields"])

    def test_unknown_moq_refuses_quantity(self) -> None:
        self._prepare(moq=None)
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIn("minimum_order_quantity", line["missing_fields"])

    def test_unknown_multiple_is_not_assumed_to_be_one(self) -> None:
        self._prepare(multiple=None)
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIn("order_multiple", line["missing_fields"])
        self.assertEqual(line["purchase_parameters"]["order_multiple_status"], "unknown")

    def test_explicit_no_multiple_allows_exact_net_quantity(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "0.4"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"), multiple=None, multiple_applicable=False)
        line = self._line(self._query(1))
        self.assertEqual(line["suggested_purchase_qty"], "0.6")
        self.assertIsNone(line["effective_order_multiple"])
        self.assertEqual(line["purchase_parameters"]["order_multiple_status"], "not_applicable")

    def test_unknown_packaging_constraint_refuses_quantity(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"), packaging_applicable=None)
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIn("packaging_multiple", line["missing_fields"])

    def test_missing_safety_stock_does_not_become_zero(self) -> None:
        self._prepare(safety=None)
        line = self._line(self._query())
        self.assertEqual(line["shortage"], "90")
        self.assertIsNone(line["safety_stock_qty"])
        self.assertIsNone(line["suggested_purchase_qty"])

    def test_unknown_inventory_does_not_create_shortage_or_purchase_quantity(self) -> None:
        self._prepare(stock=None)
        line = self._line(self._query())
        self.assertIsNone(line["shortage"])
        self.assertIsNone(line["suggested_purchase_qty"])

    def test_no_authoritative_inbound_is_not_assumed_to_be_zero(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"))
        line = self._line(self._query())
        self.assertIsNone(line["eligible_inbound_qty"])
        self.assertIsNone(line["shortage"])
        self.assertIsNone(line["suggested_purchase_qty"])

    def test_inbound_after_start_is_explicitly_excluded(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"], quantity="80", arrival="2026-10-21")
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"))
        line = self._line(self._query())
        self.assertEqual(line["eligible_inbound_qty"], "0")
        self.assertEqual(line["suggested_purchase_qty"], "90")

    def test_long_lead_time_risk_and_stable_order(self) -> None:
        self._bom([("MAT-001", "1"), ("MAT-002", "1")])
        self._inventory({"MAT-001": "0", "MAT-002": "90"})
        self._inbound(["MAT-001", "MAT-002"])
        for code, lead in (("MAT-001", 3), ("MAT-002", 8)):
            self._policy(code)
            self._parameters(code, self._price(code), lead=lead)
        first = self._query()
        second = self._query()
        self.assertEqual(first, second)
        lines = first["data"]["recommendations"]
        self.assertEqual([line["material"] for line in lines], ["MAT-002", "MAT-001"])
        self.assertEqual([line["risk_level"] for line in lines], ["high", "general"])
        self.assertEqual([line["priority"] for line in lines], [1, 2])

    def test_even_short_lead_is_high_risk_if_not_before_start(self) -> None:
        self._prepare(lead=3)
        result = self.service.query("PRODUCT", "V1", DAY, 100, "2026-10-04", as_of=AT)
        self.assertEqual(self._line(result)["risk_level"], "high")
        self.assertIn("按交期计算的到货日未早于开工日", self._line(result)["risk_reasons"])

    def test_unknown_lead_time_is_not_given_fake_risk(self) -> None:
        self._prepare(lead=None)
        line = self._line(self._query())
        self.assertIsNone(line["lead_time_days"])
        self.assertIsNone(line["earliest_arrival_date"])
        self.assertIsNone(line["risk_level"])

    def test_same_currency_cost_breaks_otherwise_equal_priority(self) -> None:
        self._bom([("MAT-001", "1"), ("MAT-002", "1")])
        self._inventory({"MAT-001": "10", "MAT-002": "10"})
        self._inbound(["MAT-001", "MAT-002"])
        for code, price in (("MAT-001", "1"), ("MAT-002", "10")):
            self._policy(code)
            self._parameters(code, self._price(code, price))
        result = self._query()
        self.assertEqual(result["data"]["recommendations"][0]["material"], "MAT-002")
        self.assertEqual(result["data"]["total_purchase_cost"], "990")

    def test_different_currencies_are_not_summed_or_compared(self) -> None:
        self._bom([("MAT-001", "1"), ("MAT-002", "1")])
        self._inventory({"MAT-001": "10", "MAT-002": "10"})
        self._inbound(["MAT-001", "MAT-002"])
        for code, currency in (("MAT-001", "CNY"), ("MAT-002", "USD")):
            self._policy(code)
            self._parameters(code, self._price(code, currency=currency))
        result = self._query()
        self.assertIsNone(result["data"]["total_purchase_cost"])
        self.assertEqual(result["data"]["known_cost_subtotals_by_currency"], {"CNY": "225.00", "USD": "225.00"})
        self.assertFalse(result["data"]["cost_ranking_applied"])

    def test_partial_prices_do_not_establish_total_cost_currency(self) -> None:
        self._bom([("MAT-001", "1"), ("MAT-002", "1")])
        self._inventory({"MAT-001": "10", "MAT-002": "10"})
        self._inbound(["MAT-001", "MAT-002"])
        for code in ("MAT-001", "MAT-002"):
            self._policy(code)
            self._parameters(code, self._price(code) if code == "MAT-001" else None)
        result = self._query()
        self.assertIsNone(result["data"]["total_purchase_cost"])
        self.assertIsNone(result["data"]["total_cost_currency"])
        self.assertEqual(result["data"]["known_cost_subtotals_by_currency"], {"CNY": "225.00"})
        self.assertFalse(result["completeness"]["single_currency"])

    def test_provenance_includes_all_six_fact_sources(self) -> None:
        self._prepare()
        source = self._line(self._query())["provenance"]
        for field in ("inventory", "inbound", "safety_stock", "parameters", "price"):
            self.assertEqual(source[field]["content_sha256"], "c" * 64)
            self.assertTrue(source[field]["import_batch_id"])
        self.assertEqual(source["bom_paths"][0][0]["provenance"]["row_number"], 2)
        self.assertEqual(source["parameters"]["source_file"], "MAT-001-parameters.xlsx")

    def test_multilevel_bom_reused_for_leaf_procurement(self) -> None:
        self._bom([("MODULE", "2")])
        self._bom([("MAT-001", "3")], parent="MODULE")
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"))
        line = self._line(self._query(10))
        self.assertEqual(line["required_qty"], "60")
        self.assertEqual(line["suggested_purchase_qty"], "50")
        self.assertEqual(len(line["provenance"]["bom_paths"][0]), 2)

    def test_multiple_supplier_parameters_require_explicit_selection(self) -> None:
        self._prepare()
        self._parameters("MAT-001", self._price("MAT-001", "3", supplier="SUP-2"), supplier="SUP-2")
        ambiguous = self._line(self._query())
        self.assertIsNone(ambiguous["supplier"])
        self.assertIsNone(ambiguous["suggested_purchase_qty"])
        selected = self._line(self._query(suppliers={"MAT-001": "SUP-2"}))
        self.assertEqual(selected["supplier"], "SUP-2")
        self.assertEqual(selected["purchase_cost"], "270")

    def test_price_unit_missing_or_wrong_scope_prevents_cost(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001", unit=None))
        line = self._line(self._query())
        self.assertEqual(line["suggested_purchase_qty"], "90")
        self.assertIsNone(line["purchase_cost"])
        self.assertIn("price.unit", line["missing_fields"])

    def test_expired_price_remains_auditable_but_is_not_used(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001", end="2026-09-30"))
        line = self._line(self._query())
        self.assertIsNone(line["purchase_cost"])
        self.assertIn("price.effective_period", line["missing_fields"])
        self.assertIsNotNone(line["provenance"]["price"])

    def test_supplier_scope_conflict_rejects_price_without_changing_quantity(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001", supplier="OTHER-SUPPLIER"))
        line = self._line(self._query())
        self.assertEqual(line["suggested_purchase_qty"], "90")
        self.assertIsNone(line["purchase_cost"])
        self.assertIn("price.supplier_scope", line["missing_fields"])

    def test_invalid_price_is_not_estimated(self) -> None:
        self._prepare(price="NaN")
        line = self._line(self._query())
        self.assertEqual(line["suggested_purchase_qty"], "90")
        self.assertIsNone(line["purchase_cost"])
        self.assertIn("price.unit_price", line["missing_fields"])

    def test_unpublished_price_cannot_supply_cost(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001", status="staging"))
        line = self._line(self._query())
        self.assertIsNone(line["purchase_cost"])
        self.assertIn("published_price", line["missing_fields"])

    def test_negative_moq_and_zero_multiple_refuse_quantity(self) -> None:
        self._prepare(moq="-1", multiple="0")
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIn("minimum_order_quantity", line["missing_fields"])
        self.assertIn("order_multiple", line["missing_fields"])

    def test_expired_parameters_are_not_replaced_by_guesses(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"), end="2026-09-30")
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIsNone(line["supplier"])

    def test_missing_supplier_stays_unknown(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"), supplier=None)
        line = self._line(self._query())
        self.assertIsNone(line["supplier"])
        self.assertIn("supplier_code", line["missing_fields"])
        self.assertFalse(line["completeness"]["parameters"])

    def test_incoherent_stock_and_inbound_do_not_form_procurement_quantity(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"}, at="2026-09-30T00:00:00+00:00")
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"))
        line = self._line(self._query())
        self.assertIsNone(line["shortage"])
        self.assertIsNone(line["suggested_purchase_qty"])

    def test_unpublished_parameters_are_ignored(self) -> None:
        self._bom([("MAT-001", "1")])
        self._inventory({"MAT-001": "10"})
        self._inbound(["MAT-001"])
        self._policy("MAT-001")
        self._parameters("MAT-001", self._price("MAT-001"), status="staging")
        line = self._line(self._query())
        self.assertIsNone(line["suggested_purchase_qty"])
        self.assertIn("purchase_parameters", line["missing_fields"])

    def test_new_tool_is_independent_and_matches_service(self) -> None:
        self._prepare()
        self.assertTrue({tool.name for tool in PUBLISHED_PURCHASE_TOOLS}.isdisjoint({tool.name for tool in FACT_QUERY_TOOLS + ALL_AGENT_TOOLS}))
        with patch.dict(os.environ, {"PMC_FACT_DATABASE_URL": f"sqlite:///{self.database.as_posix()}"}):
            result = published_purchase_recommendations_query.invoke(dict(product="PRODUCT", revision="V1", effective_date=DAY,
                                                                        quantity=100, start_date="2026-10-20", as_of=AT))
        self.assertEqual(result, self._query())

    def test_query_error_does_not_leak_exception(self) -> None:
        with patch("tools.published_purchase_tools.create_fact_store", side_effect=RuntimeError("secret database exception")):
            result = published_purchase_recommendations_query.invoke(dict(product="PRODUCT", revision="V1", effective_date=DAY,
                                                                        quantity=100, start_date="2026-10-20", as_of=AT))
        self.assertEqual(result["status"], "query_failed")
        self.assertNotIn("secret", str(result))
        self.assertIsNone(result["data"])

    def test_invalid_quantity_and_missing_bom_return_no_recommendations(self) -> None:
        self.assertEqual(self._query(0)["status"], "invalid_query")
        result = self._query()
        self.assertEqual(result["status"], "data_unavailable")
        self.assertIsNone(result["data"])

    def test_migration_preserves_old_prices_without_inventing_new_metadata(self) -> None:
        migrations = self.root / "old-migrations" / "sqlite"
        migrations.mkdir(parents=True)
        for source in (MIGRATIONS_ROOT / "sqlite").glob("*.sql"):
            if source.name < "006":
                shutil.copyfile(source, migrations / source.name)
        store = SQLiteFactStore(self.root / "old.db")
        facts = FactRepository(store)
        with patch("repositories.fact_store.MIGRATIONS_ROOT", migrations.parent):
            facts.migrate()
        item = _seed_item(facts, "OLD-ITEM")
        with store.transaction() as connection:
            batch, source = store.execute(connection, "SELECT import_batch_id, source_file_id FROM items WHERE id = ?", (item,)).fetchone()
            store.execute(connection,
                "INSERT INTO price_records (id, item_id, tax_included_unit_price, currency, effective_from, import_batch_id, source_file_id, source_sheet, source_row_number) "
                "VALUES ('old-price', ?, '1.25', 'CNY', '2026-09-01', ?, ?, '价格', 2)", (item, batch, source))
        self.assertEqual(facts.migrate(), ["006_published_purchase_planning", "007_agent_conversations", "008_bom_import_context", "009_incomplete_bom_units", "010_structural_bom_publication"])
        self.assertEqual(facts.migrate(), [])
        with store.transaction() as connection:
            row = store.execute(connection, "SELECT tax_included_unit_price, unit, supplier_code, effective_to FROM price_records").fetchone()
        self.assertEqual(row, ("1.25", None, None, None))


if __name__ == "__main__":
    unittest.main()
