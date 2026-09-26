import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const dataDirectory = path.join(projectDirectory, "data");

const workbooks = [
  {
    fileName: "bom.xlsx",
    sheetName: "BOM",
    tableName: "BomData",
    headers: ["parent_material", "child_material", "qty_per"],
    rows: [
      ["ABC-1000", "主板", 1],
      ["ABC-1000", "电机", 2],
      ["ABC-1000", "螺丝", 8],
    ],
  },
  {
    fileName: "inventory.xlsx",
    sheetName: "Inventory",
    tableName: "InventoryData",
    headers: ["material", "stock", "reserved", "incoming", "safety_stock"],
    rows: [
      ["主板", 800, 0, 0, 100],
      ["电机", 3000, 0, 0, 200],
      ["螺丝", 20000, 0, 0, 1000],
      ["传感器", 100, 20, 50, 10],
    ],
  },
  {
    fileName: "purchase.xlsx",
    sheetName: "Purchase",
    tableName: "PurchaseData",
    headers: ["material", "safety_stock", "lead_time_days"],
    rows: [
      ["主板", 100, 20],
      ["电机", 200, 15],
      ["螺丝", 1000, 7],
      ["传感器", 10, 10],
    ],
  },
];

await fs.mkdir(dataDirectory, { recursive: true });

for (const definition of workbooks) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(definition.sheetName);
  sheet.showGridLines = false;

  const values = [definition.headers, ...definition.rows];
  const range = sheet.getRangeByIndexes(0, 0, values.length, definition.headers.length);
  range.values = values;
  range.format.font = { name: "Arial", size: 10 };
  range.format.verticalAlignment = "center";
  range.format.borders = { preset: "outside", style: "thin", color: "#D9D9D9" };

  const headerRange = sheet.getRangeByIndexes(0, 0, 1, definition.headers.length);
  headerRange.format = {
    fill: "#1F4E78",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  headerRange.format.rowHeight = 22;

  const numericColumnStart = 1;
  if (definition.headers.length > numericColumnStart) {
    sheet
      .getRangeByIndexes(1, numericColumnStart, definition.rows.length, definition.headers.length - numericColumnStart)
      .format.numberFormat = "#,##0";
  }
  range.format.autofitColumns();
  range.format.autofitRows();
  sheet.freezePanes.freezeRows(1);
  sheet.tables.add(
    sheet.getRangeByIndexes(0, 0, values.length, definition.headers.length).address,
    true,
    definition.tableName,
  );

  workbook.recalculate();
  const check = await workbook.inspect({
    kind: "table",
    range: `${definition.sheetName}!A1:${String.fromCharCode(64 + definition.headers.length)}${values.length}`,
    include: "values,formulas",
    tableMaxRows: 10,
    tableMaxCols: 6,
  });
  if (!check.ndjson.includes(definition.headers[0])) {
    throw new Error(`${definition.fileName} verification failed`);
  }

  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(path.join(dataDirectory, definition.fileName));
}
