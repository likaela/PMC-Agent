import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const outputDirectory = path.join(projectDirectory, "data", "templates");
const outputPath = path.join(outputDirectory, "material_purchase_parameters.xlsx");
const headers = [
  "material_code",
  "supplier_code",
  "supplier_name",
  "safety_stock",
  "lead_time_days",
  "min_order_qty",
  "order_multiple",
  "unit_price",
  "preferred_supplier",
  "effective_from",
  "effective_to",
  "remark",
];

await fs.mkdir(outputDirectory, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("PurchaseParameters");
sheet.showGridLines = false;

const headerRange = sheet.getRangeByIndexes(0, 0, 1, headers.length);
headerRange.values = [headers];
headerRange.format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
headerRange.format.rowHeight = 24;
headerRange.format.wrapText = true;
headerRange.format.borders = { preset: "outside", style: "thin", color: "#D9E2F3" };

const inputRange = sheet.getRangeByIndexes(1, 0, 30, headers.length);
inputRange.format = {
  fill: "#FFFFFF",
  font: { name: "Arial", size: 10, color: "#1F1F1F" },
  verticalAlignment: "center",
  borders: { preset: "inside", style: "thin", color: "#D9E2F3" },
};
inputRange.format.rowHeight = 20;
sheet.getRange("A:A").format.columnWidth = 18;
sheet.getRange("B:B").format.columnWidth = 18;
sheet.getRange("C:C").format.columnWidth = 22;
sheet.getRange("D:H").format.columnWidth = 16;
sheet.getRange("I:I").format.columnWidth = 18;
sheet.getRange("J:K").format.columnWidth = 16;
sheet.getRange("L:L").format.columnWidth = 28;
sheet.getRange("D2:H31").format.numberFormat = "0.00";
sheet.getRange("J2:K31").format.numberFormat = "yyyy-mm-dd";
sheet.freezePanes.freezeRows(1);
sheet.tables.add("A1:L31", true, "MaterialPurchaseParameters");

workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "table",
  range: "PurchaseParameters!A1:L6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 12,
});
if (!inspection.ndjson.includes("material_code") || !inspection.ndjson.includes("lead_time_days")) {
  throw new Error("采购补数表模板验证失败");
}

const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputPath);
