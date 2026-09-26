import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("请提供审计 JSON 文件路径");
}
const outputPath = path.join(projectDirectory, "data", "normalized", "bom_inventory_source_audit.xlsx");
const audit = JSON.parse(await fs.readFile(sourcePath, "utf8"));

const workbook = Workbook.create();
const fontName = "Arial";
const headerFormat = {
  fill: "#1F4E78",
  font: { name: fontName, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
const bodyFormat = {
  font: { name: fontName, size: 10, color: "#1F1F1F" },
  verticalAlignment: "center",
};

const auditHeaders = [
  "material_code",
  "material_name",
  "in_main_inventory_sheet",
  "in_resistor_capacitor_sheet",
  "in_finished_goods_sheet",
  "in_historical_inventory",
  "in_material_master",
  "main_inventory_stock",
  "other_source_stock",
  "current_mrp_status",
];
const auditSheet = workbook.worksheets.add("BOM库存审计");
auditSheet.showGridLines = false;
const auditValues = [
  auditHeaders,
  ...audit.records.map((record) => auditHeaders.map((header) => record[header])),
];
auditSheet.getRangeByIndexes(0, 0, auditValues.length, auditHeaders.length).values = auditValues;
auditSheet.getRangeByIndexes(0, 0, 1, auditHeaders.length).format = headerFormat;
auditSheet.getRangeByIndexes(1, 0, auditValues.length - 1, auditHeaders.length).format = bodyFormat;
auditSheet.getRange("H2:I67").format.numberFormat = "#,##0.##";
auditSheet.getRange("A:A").format.columnWidth = 18;
auditSheet.getRange("B:B").format.columnWidth = 20;
auditSheet.getRange("C:G").format.columnWidth = 15;
auditSheet.getRange("H:I").format.columnWidth = 18;
auditSheet.getRange("J:J").format.columnWidth = 40;
auditSheet.getRangeByIndexes(0, 0, 1, auditHeaders.length).format.rowHeight = 34;
auditSheet.getRangeByIndexes(1, 0, auditValues.length - 1, auditHeaders.length).format.rowHeight = 20;
auditSheet.getRangeByIndexes(0, 0, auditValues.length, auditHeaders.length).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D9E2F3",
};
auditSheet.freezePanes.freezeRows(1);
auditSheet.freezePanes.freezeColumns(2);
auditSheet.tables.add(`A1:J${auditValues.length}`, true, "BomInventorySourceAudit");
auditSheet.getRange("J2:J67").conditionalFormats.add("containsText", {
  text: "MRP 库存数据缺失",
  format: { fill: "#FCE4D6", font: { color: "#C00000", bold: true } },
});
auditSheet.getRange("J2:J67").conditionalFormats.add("containsText", {
  text: "未参与一期 MRP",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});

const missingHeaders = [
  "material_code",
  "material_name",
  "other_inventory_sources",
  "other_source_stock",
  "possible_duplicate_inventory_source",
  "safe_for_phase_one_available_stock",
  "reason",
];
const missingSheet = workbook.worksheets.add("主库存缺失说明");
missingSheet.showGridLines = false;
const missingValues = [
  missingHeaders,
  ...audit.missing_main_inventory.map((record) => missingHeaders.map((header) => record[header])),
];
missingSheet.getRangeByIndexes(0, 0, missingValues.length, missingHeaders.length).values = missingValues;
missingSheet.getRangeByIndexes(0, 0, 1, missingHeaders.length).format = headerFormat;
missingSheet.getRangeByIndexes(1, 0, missingValues.length - 1, missingHeaders.length).format = bodyFormat;
missingSheet.getRange("D2:D23").format.numberFormat = "#,##0.##";
missingSheet.getRange("A:A").format.columnWidth = 18;
missingSheet.getRange("B:B").format.columnWidth = 20;
missingSheet.getRange("C:C").format.columnWidth = 24;
missingSheet.getRange("D:D").format.columnWidth = 18;
missingSheet.getRange("E:E").format.columnWidth = 36;
missingSheet.getRange("F:F").format.columnWidth = 18;
missingSheet.getRange("G:G").format.columnWidth = 62;
missingSheet.getRangeByIndexes(0, 0, 1, missingHeaders.length).format.rowHeight = 34;
missingSheet.getRangeByIndexes(1, 0, missingValues.length - 1, missingHeaders.length).format.rowHeight = 54;
missingSheet.getRangeByIndexes(0, 0, missingValues.length, missingHeaders.length).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D9E2F3",
};
missingSheet.getRange("E2:G23").format.wrapText = true;
missingSheet.freezePanes.freezeRows(1);
missingSheet.freezePanes.freezeColumns(2);
missingSheet.tables.add(`A1:G${missingValues.length}`, true, "MissingMainInventoryExplanation");

workbook.recalculate();
const check = await workbook.inspect({
  kind: "table",
  range: "BOM库存审计!A1:J8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 10,
});
if (!check.ndjson.includes("material_code") || !check.ndjson.includes("current_mrp_status")) {
  throw new Error("BOM 库存来源审计表结构验证失败");
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
