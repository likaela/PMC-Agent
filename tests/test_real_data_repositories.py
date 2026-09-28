import unittest

from repositories.material_master_repository import index_material_master, load_material_master_records
from repositories.real_bom_repository import load_real_bom_data, load_real_bom_relationships
from repositories.real_data_quality import build_real_data_quality_report
from repositories.real_inventory_repository import aggregate_real_inventory, load_real_inventory_data, load_real_inventory_details
from repositories.supplier_repository import load_supplier_master
from services.bom_service import explode_bom
from services.mrp_service import analyze_mrp


class RealDataRepositoryTests(unittest.TestCase):
    def test_real_bom_imports_66_relationships_from_metadata(self) -> None:
        payload = load_real_bom_relationships(expected_parent_material="KQ-Z112", expected_version="V01")
        self.assertEqual(payload["parent_material"], "KQ-Z112")
        self.assertEqual(payload["version"], "V01")
        self.assertEqual(len(payload["relationships"]), 66)

    def test_all_real_bom_materials_match_material_master(self) -> None:
        bom_codes = set(load_real_bom_data()["KQ-Z112"])
        material_master = index_material_master(load_material_master_records())
        self.assertTrue(bom_codes.issubset(material_master))

    def test_inventory_multilocation_and_multibatch_are_aggregated_once(self) -> None:
        aggregated = aggregate_real_inventory(
            [
                {"material_code": "M-001", "stock": 10, "site": "天津", "location": "A", "batch": "B1"},
                {"material_code": "M-001", "stock": 5, "site": "北京", "location": "C", "batch": "B2"},
            ]
        )
        self.assertEqual(aggregated["M-001"]["stock"], 15)
        self.assertEqual(len(aggregated["M-001"]["details"]), 2)

    def test_required_missing_inventory_codes_are_explicitly_reported(self) -> None:
        report = build_real_data_quality_report()
        self.assertTrue(
            set(report["required_missing_inventory_codes"]).issubset(report["unmatched_inventory_material_codes"])
        )
        self.assertTrue(report["required_missing_inventory_codes_confirmed"])

    def test_only_inventory_sheet_is_used_for_real_inventory(self) -> None:
        details = load_real_inventory_details()
        self.assertTrue(details)
        self.assertEqual({detail["source_sheet"] for detail in details}, {"库存表"})

    def test_supplier_master_does_not_create_purchase_parameters(self) -> None:
        supplier = load_supplier_master()[0]
        self.assertIn("supplier_code", supplier)
        self.assertIn("supplier_name", supplier)
        self.assertNotIn("material_code", supplier)
        self.assertNotIn("lead_time_days", supplier)
        self.assertNotIn("safety_stock", supplier)

    def test_mrp_uses_repository_output_without_hidden_inventory_defaults(self) -> None:
        requirements = explode_bom("KQ-Z112", 1, load_real_bom_data())
        inventory_data = load_real_inventory_data()
        matched_material = next(code for code in requirements if code in inventory_data)
        result = analyze_mrp({matched_material: requirements[matched_material]}, inventory_data)
        self.assertEqual(result["materials"][0]["material"], matched_material)
        self.assertIn("source_assumptions", inventory_data[matched_material])


if __name__ == "__main__":
    unittest.main()
