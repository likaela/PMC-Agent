import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";

const response = () => envelope("production_capacity", {
  calculation_scope: "excel_book_observation", product: "EXAMPLE-A", revision: "V01",
  requested_quantity: 100, product_unit: "片", total_material_count: 2,
  matched_material_count: 1, comparable_material_count: 0,
  source_summary: { record_count: 1, duplicate_observation_count: 0 },
  materials: [
    { material_code: "EXAMPLE-M1", required_qty: "200.000", recorded_stock_qty: "123.450",
      available_qty: null, reserved_qty: null, book_difference: null, book_shortage_qty: null,
      record_count: 1, record_found: true, unit: "片", inventory_unit: null,
      comparison_status: "pending_unit_verification", details: [] },
    { material_code: "EXAMPLE-M2", required_qty: "100", recorded_stock_qty: null,
      available_qty: null, book_difference: null, book_shortage_qty: null, record_count: 0,
      record_found: false, unit: "片", inventory_unit: null, comparison_status: "no_record", details: [] },
  ],
}, { answer: "账面记录核对，不是生产许可。" });

test("账面数量保持Decimal/null，不冒充可用库存或缺口", () => {
  const payload = response(); const original = JSON.stringify(payload);
  const vm = adaptBackendResponse(payload);
  expect(vm.bookObservation).toBe(true);
  expect(vm.materials[0].recordedStock).toBe("123.450");
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[0].bookDifference).toBeNull();
  expect(vm.materials[0].shortage).toBeNull();
  expect(vm.materials[1].recordedStock).toBeNull();
  expect(vm.materials[1].recordFound).toBe(false);
  expect(vm.status).not.toBe("ready");
  expect(JSON.stringify(payload)).toBe(original);
});

test("账面来源明确标记Excel观察，不冒充已发布快照", () => {
  const payload = response();
  payload.provenance = { source_file: "synthetic.xlsx", source_kind: "excel_observation",
    sheet_name: "库存表", row_number: 2, snapshot_at: null, content_sha256: "a".repeat(64) };
  const vm = adaptBackendResponse(payload);
  expect(vm.sources[0].kind).toBe("Excel账面记录");
  expect(vm.sources[0].snapshotAt).toBeNull();
  expect(vm.sources[0].row).toBe("2");
});

test("人工确认片仅作为显示单位，数量与available null均不改变", () => {
  const payload = response();
  const data = payload.structured_data!.data as Record<string, any>;
  data.source_summary.unit_confirmation = { unit: "片", source_kind: "human_business_confirmation" };
  data.materials[0].inventory_unit = "片";
  data.materials[0].details = [{ material_code: "EXAMPLE-M1", recorded_stock_qty: "123.450", inventory_unit: "片",
    provenance: { row_number: 2 }, duplicate_observation: false }];
  const vm = adaptBackendResponse(payload);
  expect(vm.materials[0].inventoryUnit).toBe("片");
  expect(vm.materials[0].recordedStock).toBe("123.450");
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[1].recordedStock).toBeNull();
  expect(vm.metrics).toContainEqual({ label: "库存数量口径", value: "片" });
  expect(vm.detailTable?.rows[0][4]).toBe("片");
  expect(vm.nextAction).not.toContain("库存计量单位");
});

test("企业首页仅宣传本轮交付，合成采购入口仍保留", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.locator(".home-page")).toContainText("BOM与生产需求查询");
  await expect(page.locator(".home-page")).toContainText("Excel库存记录查询");
  await expect(page.locator(".home-page")).toContainText("连续追问与来源查询");
  await expect(page.locator(".home-page")).not.toContainText("采购需求分析");
});

test("企业物料表显示片、原始数量与未知，不展示差额采购承诺", async ({ page }) => {
  const payload = response();
  const data = payload.structured_data!.data as Record<string, any>;
  data.source_summary.unit_confirmation = { unit: "片" };
  data.materials[0].inventory_unit = "片";
  data.materials[0].book_difference = "-76.550";
  await page.route("**/api/v1/agent/sessions", route => route.fulfill({ json: { ...session, session_id: "test-unit-session" } }));
  await page.route("**/api/v1/agent/query", route => route.fulfill({ json: { ...payload, session_id: "test-unit-session" } }));
  await page.goto("/#/workspace");
  await page.getByLabel("输入分析问题").fill("查询EXAMPLE-A库存");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(2);
  await expect(page.locator(".materials-card tbody tr").first()).toContainText("123.45");
  await expect(page.locator(".materials-card tbody tr").first()).toContainText("片");
  await expect(page.locator(".materials-card tbody tr").nth(1)).toContainText("无记录");
  await expect(page.locator(".materials-card")).not.toContainText("账面差额");
  await expect(page.locator(".materials-card")).not.toContainText("建议采购量");
  await expect(page.locator(".materials-card")).not.toContainText("单位未核验");
});
