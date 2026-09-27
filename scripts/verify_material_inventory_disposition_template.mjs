import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const inputPath = path.join(projectDirectory, "data", "templates", "material_inventory_disposition.xlsx");
const previewPath = path.join(os.tmpdir(), "pmc-agent-material-inventory-disposition.png");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const check = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 5,
  tableMaxCols: 7,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 30 },
  summary: "库存确认模板公式错误扫描",
});
const preview = await workbook.render({
  sheetName: "Dispositions",
  range: "A1:G10",
  scale: 1.5,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(check.ndjson);
console.log(errors.ndjson);
console.log(`preview=${previewPath}`);
