import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";

const internal = /保留\d+项|排除\d+项|原66项|没有合成补充|精简评审|评审子集|评委特供|真实企业产品|合成演示/;
test("历史结构结果使用业务表达，数值与未知语义不改变", () => {
  const response = envelope("production_capacity", {
    calculation_scope:"excel_book_observation", slim_review:true, quantity_review:true,
    product:"EXAMPLE-A", revision:"V01", product_unit:"片", total_material_count:34,
    original_material_count:66, excluded_material_count:32, dataset_version:"example-version",
    requested_quantity:1, theoretical_max_quantity:1, synthetic:false,
    inventory_sufficient_for_requested:true, quantity_check_status:"sufficient",
    materials:[], book_shortages:[], limiting_materials:[],
  }, {answer:"精简评审子集保留34项／原66项，排除32项，没有合成补充。"});
  const original = JSON.stringify(response);
  const view = adaptBackendResponse(response, "为什么？");
  expect(view.answer).toContain("当前分析范围：34项物料");
  expect(view.answer).toContain("满足生产1片");
  expect(JSON.stringify({answer:view.answer,metrics:view.metrics,title:view.title,warnings:view.warnings})).not.toMatch(internal);
  expect(view.conclusion).toContain("不代表完整产品生产放行");
  expect(JSON.stringify(response)).toBe(original);
});

test("产品目录仅以演示产品区分，不伪装数据性质", () => {
  const r = envelope("fact_query", { products:[
    {product_code:"EXAMPLE-A", product_name:null, published_bom_status:"published", revisions:[{revision:"V01"}]},
    {product_code:"DEMO-PMC-01", product_name:null, published_bom_status:"synthetic", synthetic:true, revisions:[{revision:"V01"}]},
  ]});
  r.structured_data!.query_type = "product_search";
  const vm = adaptBackendResponse(r);
  const statusColumn = vm.detailTable!.columns.indexOf("BOM状态");
  expect(vm.detailTable?.rows[0][statusColumn]).toBe("已发布");
  expect(vm.detailTable?.rows[1][statusColumn]).toBe("演示产品");
  expect(vm.answer).toContain("DEMO-PMC-01（演示产品）");
  expect(vm.answer).not.toMatch(internal);
  expect((r.structured_data!.data as any).products[1].synthetic).toBe(true);
});

test("智能查询默认收起、点选收起、新会话及刷新保持紧凑，窄屏不溢出", async ({page}) => {
  await page.route("**/api/v1/agent/resolve", r => r.fulfill({json:{status:"ok",product_code:null,catalog_query:true}}));
  let calls = 0;
  await page.route("**/api/v1/agent/catalog", r => r.fulfill({json:{products:[{
    product_code:"EXAMPLE-A", synthetic:false, default_mode:"full",
    modes:[{mode:"full",label:"完整追溯范围",scenario_id:null,line_count:66,dataset_version:null}],
  }]}}));
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({json:session}));
  await page.route("**/api/v1/agent/query", r => {
    calls++;
    return r.fulfill({json:{...envelope("fact_query", {products:[]}),session_id:session.session_id}});
  });
  await page.goto("/#/workspace");
  const toggle = page.getByRole("button", {name:"展开推荐问题"});
  await expect(toggle).toHaveAttribute("aria-expanded","false");
  await expect(page.locator(".quick-questions")).toHaveCount(0);
  const closed = (await page.locator(".smart-queries").boundingBox())!.height;
  await toggle.click();
  await expect(page.getByRole("button", {name:"收起",exact:true})).toHaveAttribute("aria-expanded","true");
  expect((await page.locator(".smart-queries").boundingBox())!.height).toBeGreaterThan(closed);
  await page.locator(".quick-questions").getByRole("button", {name:"查看BOM"}).click();
  await expect(toggle).toBeVisible();
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  expect(calls).toBe(1);
  await page.getByRole("button", {name:"新建分析",exact:true}).click();
  await expect(toggle).toHaveAttribute("aria-expanded","false");
  await page.setViewportSize({width:390,height:844});
  await toggle.click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-expanded","false");
});
