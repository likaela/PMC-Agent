import {test, expect} from "@playwright/test";
import {adaptBackendResponse} from "../src/services/responseAdapter";
import {envelope, inventory, production, session} from "./agentFixtures";

test("null指标省略、已知0保留，原始事实和完整性不改变", () => {
  const r = inventory();
  r.structured_data!.completeness = {available_qty:false, reserved_qty:false};
  const original = JSON.stringify(r), vm = adaptBackendResponse(r, "查库存");
  expect(vm.metrics?.every(m => m.value != null)).toBe(true);
  expect(vm.metrics?.some(m => /可用|预留|待核实|最大/.test(m.label))).toBe(false);
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[0].onHand).toBe("100.000");
  expect(vm.completeness!.available_qty).toBe(false);
  expect(JSON.stringify(r)).toBe(original);
});

test("部分产量上限与完整BOM结论分别映射，不猜最大数量", () => {
  const r = envelope("production_capacity", {calculation_scope:"excel_book_observation", product:"EXAMPLE", revision:"R1", product_unit:"片",
    capacity_query:true, quantity_review:true, total_material_count:3, matched_material_count:2, comparable_material_count:1,
    verified_material_count:1, verified_material_capacity:8, theoretical_max_quantity:null, full_bom_capacity_determined:false,
    requested_quantity:null, materials:[], source_summary:{}});
  let vm = adaptBackendResponse(r, "最多能生产多少片");
  expect(vm.metrics?.find(m => m.label === "已核算物料产量上限")?.value).toBe("8");
  expect(vm.metrics?.some(m => m.label === "完整BOM最大满足数量")).toBe(false);
  expect(vm.quantity).toBeNull();
  const data = r.structured_data!.data as Record<string, unknown>;
  data.verified_material_capacity = 0;
  data.theoretical_max_quantity = 0;
  data.full_bom_capacity_determined = true;
  vm = adaptBackendResponse(r, "最多能生产多少片");
  expect(vm.metrics?.find(m => m.label === "完整BOM最大满足数量")?.value).toBe("0");
  expect(vm.status).toBe("blocked");
});

test("普通生产不附带最大值，明确最大查询无伪造目标", () => {
  const r = production(50);
  expect(adaptBackendResponse(r, "生产50台").metrics?.some(m => /最大/.test(m.label))).toBe(false);
  const vm = adaptBackendResponse(r, "最多可以生产多少台");
  expect(vm.metrics?.find(m => /最大/.test(m.label))?.value).toBe("75");
  expect(vm.quantity).toBeNull();
  r.structured_data!.presentation = {show_maximum:false};
  expect(adaptBackendResponse(r, "哪些物料影响最大？").metrics?.some(m => /最大/.test(m.label))).toBe(false);
});

test("来源查询不附加旧产能或物料表，证据仍可追溯", () => {
  const r = production(100);
  r.structured_data!.presentation = {result_type:"source", user_warnings:[]};
  const vm = adaptBackendResponse(r, "查看来源");
  expect(vm.metrics).toEqual([]);
  expect(vm.materials).toEqual([]);
  expect(vm.sources.length).toBeGreaterThan(0);
  expect(vm.backend).toBe(r);
});

test("整列无事实不展示，BOM不附库存产能；恢复按原问题而非新问题", async ({page}) => {
  const bom = envelope("bom", {parent_item:{material_code:"EXAMPLE",unit:null}, revision:"R1", effective_from:null, line_count:1,
    lines:[{child_item:{material_code:"PART",name:"物料"},qty_per:"1.00",unit:null,price:null}]});
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({json:session}));
  await page.route("**/api/v1/agent/query", r => r.fulfill({json:bom}));
  await page.goto("/#/workspace");
  await expect(page.locator(".summary-grid")).not.toContainText("未提供");
  await page.getByLabel("输入分析问题").fill("查询BOM");
  await page.getByRole("button", {name:"发送问题",exact:true}).click();
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  await expect(page.locator("#analysis-result")).not.toContainText("未提供");
  await expect(page.locator(".materials-card th")).not.toContainText(["可用库存","缺口数量","预留数量"]);
  await expect(page.locator(".materials-card")).toContainText("1.00");
  const before = adaptBackendResponse(production(50), "生产50台");
  expect(before.metrics?.some(m => /最大/.test(m.label))).toBe(false);
  expect(adaptBackendResponse(production(100), "最多生产多少台").metrics?.some(m => /最大/.test(m.label))).toBe(true);
  expect(before.quantity).toBe("50");
});

test("库存原行明细默认折叠，主动展开后仍有真实数量", async ({page}) => {
  const r = envelope("inventory", {product:"EXAMPLE", calculation_scope:"excel_book_observation", source_summary:{},
    materials:[{material_code:"PART",recorded_stock_qty:"12.50",inventory_unit:"片",record_count:1,record_found:true,
      details:[{material_code:"PART",recorded_stock_qty:"12.50",inventory_unit:"片",provenance:{row_number:2}}]}]});
  await page.route("**/api/v1/agent/sessions", q => q.fulfill({json:session}));
  await page.route("**/api/v1/agent/query", q => q.fulfill({json:r}));
  await page.goto("/#/workspace");
  await page.getByLabel("输入分析问题").fill("查库存");
  await page.getByRole("button",{name:"发送问题",exact:true}).click();
  const details = page.locator("#analysis-result details");
  await expect(details).not.toHaveAttribute("open");
  await page.getByText("展开库存记录明细",{exact:true}).click();
  await expect(details).toHaveAttribute("open");
  await expect(details).toContainText("12.50");
  await expect(details).not.toContainText("未提供");
});
