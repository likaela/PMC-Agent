import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const dataDirectory = path.resolve(scriptDirectory, "..", "data");
const previewDirectory = path.join(os.tmpdir(), "pmc-agent-excel-previews");
const files = [
  ["bom.xlsx", "BOM", "A1:C4"],
  ["inventory.xlsx", "Inventory", "A1:E5"],
  ["purchase.xlsx", "Purchase", "A1:C5"],
];

await fs.mkdir(previewDirectory, { recursive: true });
for (const [fileName, sheetName, range] of files) {
  const input = await FileBlob.load(path.join(dataDirectory, fileName));
  const workbook = await SpreadsheetFile.importXlsx(input);
  const check = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values,formulas",
    tableMaxRows: 10,
    tableMaxCols: 6,
  });
  const preview = await workbook.render({ sheetName, range, scale: 2, format: "png" });
  const previewPath = path.join(previewDirectory, `${fileName}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  console.log(`${fileName}: ${check.ndjson.replace(/\n/g, " ")}`);
  console.log(`preview=${previewPath}`);
}
