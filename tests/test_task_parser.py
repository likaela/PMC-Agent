import unittest

from services.task_parser_service import TaskParseError, parse_production_task


class TaskParserServiceTests(unittest.TestCase):
    def test_chinese_task_parses_product_quantity_and_default_version(self) -> None:
        task = parse_production_task("我要生产100台KQ-Z112，帮我看看能不能开工")
        self.assertEqual(
            task,
            {"product": "KQ-Z112", "bom_version": "V01", "quantity": 100},
        )

    def test_quantity_can_be_extracted_after_product_model(self) -> None:
        task = parse_production_task("请安排生产 KQ-Z112，数量为 25")
        self.assertEqual(task["quantity"], 25)

    def test_product_and_explicit_bom_version_are_extracted(self) -> None:
        task = parse_production_task("生产 2 台 kq-z112，使用 v1 BOM")
        self.assertEqual(task["product"], "KQ-Z112")
        self.assertEqual(task["bom_version"], "V01")

    def test_missing_product_or_quantity_returns_clear_error(self) -> None:
        with self.assertRaisesRegex(TaskParseError, "产品型号"):
            parse_production_task("我要生产100台")
        with self.assertRaisesRegex(TaskParseError, "生产数量"):
            parse_production_task("帮我检查KQ-Z112能否开工")

    def test_invalid_quantity_is_rejected(self) -> None:
        with self.assertRaisesRegex(TaskParseError, "正整数"):
            parse_production_task("我要生产0台KQ-Z112")


if __name__ == "__main__":
    unittest.main()
