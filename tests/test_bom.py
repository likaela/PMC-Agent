import unittest

from tools.bom_tool import explode_bom


class BomToolTests(unittest.TestCase):
    def test_abc_1000_for_1000_units_has_expected_material_requirements(self) -> None:
        self.assertEqual(
            explode_bom("ABC-1000", 1000),
            {"主板": 1000, "电机": 2000, "螺丝": 8000},
        )


if __name__ == "__main__":
    unittest.main()
