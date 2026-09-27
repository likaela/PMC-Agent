import unittest

from tools.bom_tool import explode_bom


class BomToolTests(unittest.TestCase):
    def test_abc_1000_for_1000_units_has_expected_material_requirements(self) -> None:
        self.assertEqual(
            explode_bom("ABC-1000", 1000),
            {"主板": 1000, "芯片": 4000, "电机": 2000, "螺丝": 8000},
        )

    def test_unknown_product_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有找到产品"):
            explode_bom("UNKNOWN-1000", 1000)

    def test_negative_quantity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "生产数量必须是正整数"):
            explode_bom("ABC-1000", -1)

    def test_two_level_bom_is_expanded(self) -> None:
        from services.bom_service import explode_bom as calculate_bom

        self.assertEqual(
            calculate_bom("成品", 10, {"成品": {"组件": 2}, "组件": {"零件": 3}}),
            {"零件": 60},
        )

    def test_three_level_bom_is_expanded(self) -> None:
        from services.bom_service import explode_bom as calculate_bom

        self.assertEqual(
            calculate_bom(
                "成品",
                2,
                {"成品": {"组件A": 2}, "组件A": {"组件B": 3}, "组件B": {"零件": 4}},
            ),
            {"零件": 48},
        )

    def test_same_leaf_from_multiple_paths_is_aggregated(self) -> None:
        from services.bom_service import explode_bom as calculate_bom

        self.assertEqual(
            calculate_bom(
                "成品",
                1,
                {"成品": {"组件A": 1, "组件B": 1}, "组件A": {"零件": 2}, "组件B": {"零件": 3}},
            ),
            {"零件": 5},
        )

    def test_circular_bom_is_rejected(self) -> None:
        from services.bom_service import explode_bom as calculate_bom

        with self.assertRaisesRegex(ValueError, "循环 BOM"):
            calculate_bom("A", 1, {"A": {"B": 1}, "B": {"A": 1}})


if __name__ == "__main__":
    unittest.main()
