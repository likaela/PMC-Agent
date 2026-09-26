import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const reportPath = path.join(projectDirectory, "data", "normalized", "kq_z112_real_mrp_report.json");
const outputPath = path.join(projectDirectory, "data", "templates", "material_inventory_disposition.xlsx");
const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
const headers = [
  "material_code",
  "disposition",
  "confirmed_stock",
  "include_in_mrp",
  "reason",
  "confirmed_by",
  "remark",
];
const dispositions = [
  "stock_zero",
  "non_stock_item",
  "purchase_to_order",
  "customer_supplied",
  "outsourced",
  "bom_obsolete",
  "inventory_missing",
  "pending_confirmation",
];
const pendingRows = [
  ...report.unknown_inventory_list,
  ...report.pending_confirmation_inventory_list,
].map((item) => [
  item.material,
  null,
  null,
  null,
  `当前库存状态：${item.inventory_status}`,
  null,
  null,
]);
const dataRowCount = pendingRows.length;

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Dispositions");
sheet.showGridLines = false;
const values = [headers, ...pendingRows];
sheet.getRangeByIndexes(0, 0, values.length, headers.length).values = values;
sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
if (dataRowCount) {
sheet.getRangeByIndexes(1, 0, dataRowCount, headers.length).format = {
  font: { name: "Arial", size: 10, color: "#1F1F1F" },
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#D9E2F3" },
};
sheet.getRangeByIndexes(1, 1, dataRowCount, 3).format.fill = "#FFF2CC";
sheet.getRangeByIndexes(1, 1, dataRowCount, 3).format.horizontalAlignment = "center";
sheet.getRangeByIndexes(1, 2, dataRowCount, 1).format.numberFormat = "#,##0.##";
}
sheet.getRange("A:A").format.columnWidth = 18;
sheet.getRange("B:B").format.columnWidth = 24;
sheet.getRange("C:C").format.columnWidth = 18;
sheet.getRange("D:D").format.columnWidth = 16;
sheet.getRange("E:E").format.columnWidth = 34;
sheet.getRange("F:F").format.columnWidth = 20;
sheet.getRange("G:G").format.columnWidth = 34;
sheet.getRangeByIndexes(0, 0, 1, headers.length).format.rowHeight = 28;
if (dataRowCount) {
  sheet.getRangeByIndexes(1, 0, dataRowCount, headers.length).format.rowHeight = 22;
}
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(1);
if (dataRowCount) {
  sheet.tables.add(`A1:G${values.length}`, true, "MaterialInventoryDisposition");
  sheet.getRangeByIndexes(1, 1, dataRowCount, 1).dataValidation = { rule: { type: "list", values: dispositions } };
  sheet.getRangeByIndexes(1, 3, dataRowCount, 1).dataValidation = { rule: { type: "list", values: ["TRUE", "FALSE"] } };
}

const rulesSheet = workbook.worksheets.add("Rules");
rulesSheet.showGridLines = false;
rulesSheet.getRange("A1:B9").values = [
  ["disposition", "一期处理规则"],
  ["stock_zero", "必须 confirmed_stock=0 且 include_in_mrp=TRUE，转换为 known 库存"],
  ["inventory_missing", "保留 unknown，不伪造库存"],
  ["purchase_to_order", "保留 BOM，作为独立业务状态"],
  ["customer_supplied", "保留 BOM，作为独立业务状态"],
  ["outsourced", "保留 BOM，作为独立业务状态"],
  ["non_stock_item", "保留 BOM，作为独立业务状态"],
  ["bom_obsolete", "仅 BOM 待核验预警，不自动删除关系"],
  ["pending_confirmation", "保留库存待确认状态"],
];
rulesSheet.getRange("A1:B1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
rulesSheet.getRange("A2:B9").format = {
  font: { name: "Arial", size: 10 },
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#D9E2F3" },
};
rulesSheet.getRange("A:A").format.columnWidth = 24;
rulesSheet.getRange("B:B").format.columnWidth = 62;
rulesSheet.getRange("B2:B9").format.wrapText = true;
rulesSheet.getRange("A1:B9").format.rowHeight = 28;
rulesSheet.freezePanes.freezeRows(1);

workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "table",
  range: "Dispositions!A1:G6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 7,
});
if (!inspection.ndjson.includes("material_code") || !inspection.ndjson.includes("disposition")) {
  throw new Error("库存业务确认模板验证失败");
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
