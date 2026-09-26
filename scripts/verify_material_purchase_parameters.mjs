import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const inputPath = path.join(projectDirectory, "data", "templates", "material_purchase_parameters.xlsx");
const previewPath = path.join(os.tmpdir(), "pmc-agent-purchase-parameters.png");

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const inspection = await workbook.inspect({
  kind: "table",
  range: "PurchaseParameters!A1:L6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 12,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 30 },
  summary: "采购参数模板公式错误扫描",
});
const preview = await workbook.render({
  sheetName: "PurchaseParameters",
  range: "A1:L12",
  scale: 2,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(inspection.ndjson);
console.log(errors.ndjson);
console.log(`preview=${previewPath}`);
