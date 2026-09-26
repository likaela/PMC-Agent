import unittest

from tools.bom_tool import explode_bom


class BomToolTests(unittest.TestCase):
    def test_abc_1000_for_1000_units_has_expected_material_requirements(self) -> None:
        self.assertEqual(
            explode_bom("ABC-1000", 1000),
            {"主板": 1000, "电机": 2000, "螺丝": 8000},
        )

    def test_unknown_product_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有找到产品"):
            explode_bom("UNKNOWN-1000", 1000)

    def test_negative_quantity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "生产数量必须是正整数"):
            explode_bom("ABC-1000", -1)


if __name__ == "__main__":
    unittest.main()
