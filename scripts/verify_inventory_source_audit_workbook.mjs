import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");
const inputPath = path.join(projectDirectory, "data", "normalized", "bom_inventory_source_audit.xlsx");
const previewPath = path.join(os.tmpdir(), "pmc-agent-bom-inventory-source-audit.png");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 8000,
  tableMaxRows: 4,
  tableMaxCols: 10,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "库存来源审计公式错误扫描",
});
const preview = await workbook.render({
  sheetName: "主库存缺失说明",
  range: "A1:G10",
  scale: 1.5,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(summary.ndjson);
console.log(formulaErrors.ndjson);
console.log(`preview=${previewPath}`);
