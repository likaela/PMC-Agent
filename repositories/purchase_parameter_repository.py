"""采购补数表的只读 Excel 适配器。"""

from pathlib import Path

from openpyxl import load_workbook

from repositories.normalization import normalize_header, normalize_material_code, normalize_nonnegative_number


PURCHASE_PARAMETER_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "templates" / "material_purchase_parameters.xlsx"
)
PURCHASE_PARAMETER_SHEET_NAME = "PurchaseParameters"
REQUIRED_PURCHASE_FIELDS = ("supplier_code", "safety_stock", "lead_time_days")


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def load_purchase_parameters(file_path: Path = PURCHASE_PARAMETER_FILE) -> dict[str, dict[str, object]]:
    """读取人工维护的采购补数表；空行和缺失字段以显式状态保留。"""
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        sheet = workbook[PURCHASE_PARAMETER_SHEET_NAME]
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        headers = {normalize_header(value): index for index, value in enumerate(header_row)}
        required_columns = {"material_code", *REQUIRED_PURCHASE_FIELDS}
        if not required_columns.issubset(headers):
            raise ValueError("采购补数表缺少一期必需列")

        result: dict[str, dict[str, object]] = {}
        for row in sheet.iter_rows(min_row=2, values_only=True):
            material_code = normalize_material_code(row[headers["material_code"]])
            if not material_code:
                continue
            if material_code in result:
                raise ValueError(f"采购补数表存在重复料号：{material_code}")

            supplier_code = str(row[headers["supplier_code"]] or "").strip()
            safety_value = row[headers["safety_stock"]]
            lead_time_value = row[headers["lead_time_days"]]
            missing_fields = [
                field
                for field, value in (
                    ("supplier_code", supplier_code),
                    ("safety_stock", safety_value),
                    ("lead_time_days", lead_time_value),
                )
                if _is_blank(value)
            ]
            record: dict[str, object] = {
                "material_code": material_code,
                "supplier_code": supplier_code or None,
                "safety_stock": None,
                "lead_time_days": None,
                "missing_fields": missing_fields,
            }
            if "safety_stock" not in missing_fields:
                record["safety_stock"] = normalize_nonnegative_number(safety_value, "safety_stock")
            if "lead_time_days" not in missing_fields:
                lead_time = normalize_nonnegative_number(lead_time_value, "lead_time_days")
                if not isinstance(lead_time, int):
                    raise ValueError("lead_time_days 必须是非负整数")
                record["lead_time_days"] = lead_time
            result[material_code] = record
        return result
    finally:
        workbook.close()


def get_purchase_parameter_status(
    material_code: str,
    purchase_parameters: dict[str, dict[str, object]],
) -> dict[str, object]:
    """返回物料的采购参数完整性，不从供应商主数据补全字段。"""
    record = purchase_parameters.get(material_code)
    if record is None:
        return {
            "data_status": "采购参数待补充",
            "missing_fields": list(REQUIRED_PURCHASE_FIELDS),
            "reason": "采购补数表不存在该物料记录",
        }
    missing_fields = list(record.get("missing_fields", []))
    if missing_fields:
        return {
            "data_status": "采购参数待补充",
            "missing_fields": missing_fields,
            "reason": "采购补数表字段未填写",
        }
    return {
        "data_status": "采购参数完整",
        "missing_fields": [],
        "supplier_code": record["supplier_code"],
        "safety_stock": record["safety_stock"],
        "lead_time_days": record["lead_time_days"],
    }
