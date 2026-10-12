import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";

function response() {
  return envelope("production_capacity", {
    calculation_scope: "excel_book_observation", slim_review: true, current_business: true,
    product: "EXAMPLE-CURRENT", revision: "V01-C2", product_unit: "片", dataset_version: "current-v2",
    synthetic: false, total_material_count: 2, requested_quantity: 1, theoretical_max_quantity: 7,
    matched_material_count: 2, quantity_review: true, inventory_sufficient_for_requested: true,
    quantity_check_status: "sufficient", materials: [], source_summary: {},
  });
}
test("当前BOM使用后端版本、数量，不展示旧范围或自动最大值", () => {
  const r = response(), before = JSON.stringify(r), vm = adaptBackendResponse(r, "生产1片");
  expect(vm.title).toContain("当前BOM");
  expect(vm.metrics?.find(m => m.label === "BOM版本")?.value).toBe("V01-C2");
  expect(vm.metrics?.some(m => /数据集版本|最大|排除|保留/.test(m.label))).toBe(false);
  expect(JSON.stringify(r)).toBe(before);
});
test("当前BOM最大量只能展示真实响应，不引用旧50上限", () => {
  const vm = adaptBackendResponse(response(), "最多可以生产多少片");
  expect(vm.metrics?.find(m => m.label === "最大满足数量")?.value).toBe("7片");
  expect(vm.quantity).toBeNull(); // A unit probe is not a user production target.
});
test("唯一当前配置隐藏旧范围，旧版本指针归档而不读取旧Evidence", async ({page}) => {
  const base = "http://127.0.0.1:8000", code = "EXAMPLE-CURRENT";
  const catalog = [{product_code:code, synthetic:false, default_mode:"current", modes:[{mode:"current",label:"当前BOM",scenario_id:null,line_count:2,dataset_version:"current-v2"}]}];
  let oldReads = 0;
  await page.route("**/api/v1/agent/catalog", r => r.fulfill({json:{products:catalog}}));
  await page.route("**/api/v1/agent/sessions/old", r => { oldReads++; return r.fulfill({status:404,json:{}}); });
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({json:{...session, session_id:"new-current", product_context:{product_code:code,scenario_id:null,dataset_version:"current-v2",analysis_mode:"current"}}}));
  await page.addInitScript(({base,code}) => sessionStorage.setItem("pmc-local-conversation-v3:"+base,JSON.stringify({active:"old",segments:[{session_id:"old",product_code:code,mode:"full",scenario_id:null,dataset_version:null}]})),{base,code});
  await page.goto("/#/workspace");
  await page.reload();
  await expect(page.locator("#local-review-product")).toHaveValue("");
  await page.locator("#local-review-product").selectOption(code);
  await expect(page.locator("#active-product-select")).toHaveValue(code);
  await expect(page.locator("#local-review-scope")).toHaveCount(0);
  await expect(page.locator("#data-space")).toHaveCount(0);
  expect(oldReads).toBe(0);
  expect(await page.evaluate(() => Object.keys(sessionStorage).some(k => k.includes(":archived:")))).toBe(true);
});
