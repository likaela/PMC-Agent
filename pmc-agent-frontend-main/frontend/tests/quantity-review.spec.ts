import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";
test.beforeEach(async ({page})=>{await page.route("**/api/v1/agent/catalog",r=>r.fulfill({status:404,json:{}}));});

function reply(quantity: number, failed = false) {
  return envelope("production_capacity", {
    calculation_scope: "excel_book_observation", quantity_review: !failed,
    stock_read_failed: failed, product: "EXAMPLE-A", revision: "V01",
    requested_quantity: quantity, product_unit: "片", total_material_count: 2,
    matched_material_count: failed ? 0 : 1, comparable_material_count: failed ? 0 : 1,
    quantity_check_status: "insufficient", inventory_sufficient_for_requested: false,
    source_summary: { unit_confirmation: { unit: "片" }, record_count: 1 },
    materials: [
      { material_code: "SYNTHETIC-M1", name: "合成测试物料", required_qty: `${quantity}.00`,
        recorded_stock_qty: failed ? null : "0.00", actual_stock_qty: failed ? null : "0.00",
        available_qty: null, reserved_qty: null, book_shortage_qty: failed ? null : `${quantity}.00`,
        shortage_qty: failed ? null : `${quantity}.00`, quantity_status: failed ? "unknown" : "shortage",
        comparison_status: failed ? "inventory_read_failed" : "comparable", record_count: failed ? 0 : 1,
        record_found: !failed, unit: "片", inventory_unit: failed ? null : "片", details: [] },
      { material_code: "SYNTHETIC-M2", required_qty: `${quantity * 2}`, recorded_stock_qty: null,
        available_qty: null, book_shortage_qty: null, record_found: false, unit: "片",
        comparison_status: "no_record", quantity_status: "unknown", details: [] },
    ],
  }, { status: failed ? "query_failed" : "ok", answer: `本次核对${quantity}片，部分物料不足。` });
}
const invalid = () => envelope("production_capacity", null, {
  status: "invalid_query", answer: "生产数量需要大于0且为整数。请提供1片、50片或100片。",
  structured_data: { operation: "quantity_validation", query_type: "production_capacity", data: null,
    completed_steps: [], validation_error: "quantity_must_be_positive_integer" },
});

test("实际库存数量核对映射保持零、unknown、Decimal及后端判断", () => {
  const data = reply(100); const original = JSON.stringify(data);
  const vm = adaptBackendResponse(data);
  expect(vm.quantityReview).toBe(true);
  expect(vm.status).toBe("blocked");
  expect(vm.materials[0].recordedStock).toBe("0.00");
  expect(vm.materials[0].shortage).toBe("100.00");
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[1].shortage).toBeNull();
  expect(vm.metrics?.some(m => m.label === "库存时点")).toBe(false);
  expect(JSON.stringify(data)).toBe(original);
});

test("库存异常保留本次需求，非法输入不沿用旧结果", () => {
  const failed = adaptBackendResponse(reply(50, true));
  expect(failed.materials).toHaveLength(2);
  expect(failed.materials[0].required).toBe("50.00");
  expect(failed.materials[0].recordedStock).toBeNull();
  const zero = adaptBackendResponse(invalid());
  expect(zero.validationError).toBe(true);
  expect(zero.materials).toHaveLength(0);
  expect(zero.quantity).toBeNull();
});

test("评审推演来源区分真实BOM、原Excel与合成补充", () => {
  const result=reply(50);
  result.scenario_id="review_real_bom_simulation";
  result.provenance={bom:{source_file:"example-bom.xlsx"},inventory:[
    {source_file:"example-stock.xlsx",source_kind:"excel_observation"},
    {source_file:"review-synthetic-supplement",source_kind:"synthetic_review",synthetic:true}
  ]};
  const vm=adaptBackendResponse(result);
  expect(vm.sources.map(s=>s.kind)).toEqual(["已发布事实","Excel账面记录","合成演示事实"]);
});

test("100→50→0→1消息、当前面板与刷新恢复一致", async ({ page }) => {
  const turns: any[] = [];
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({ json: { ...session, session_id: "quantity-session" } }));
  await page.route("**/api/v1/agent/sessions/quantity-session?*", r => r.fulfill({ json: {
    ...session, session_id: "quantity-session", context_version: turns.length, turns,
  } }));
  await page.route("**/api/v1/agent/query", r => {
    const body = r.request().postDataJSON();
    const quantity = body.message.includes("100") ? 100 : body.message.includes("50") ? 50 : body.message.includes("0个") ? 0 : 1;
    const response = { ...(quantity === 0 ? invalid() : reply(quantity)), session_id: "quantity-session", turn_id: `turn-${turns.length}` };
    turns.push({ turn_id: response.turn_id, sequence_no: turns.length + 1, user_query: body.message, response, created_at: session.created_at });
    return r.fulfill({ json: response });
  });
  await page.goto("/#/workspace");
  for (const [q,n] of [["生产100片EXAMPLE-A",100], ["生产50个呢",50], ["生产0个",0], ["生产1个",1]] as const) {
    await page.getByLabel("输入分析问题").fill(q);
    await page.getByRole("button",{name:"发送问题",exact:true}).click();
    if (n === 0) {
      await expect(page.locator(".result-panel")).toContainText("请调整生产数量");
      await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
      await expect(page.locator(".result-panel")).not.toContainText("本次核对50片");
    } else {
      await expect(page.locator(".result-panel")).toContainText(`本次核对${n}片`);
      await expect(page.locator(".materials-card tbody tr")).toHaveCount(2);
      await expect(page.locator(".materials-card")).toContainText("实际库存数量");
      await expect(page.locator(".materials-card")).toContainText("缺口数量");
      await expect(page.locator(".materials-card")).not.toContainText("可用库存未知");
    }
  }
  await page.reload();
  await expect(page.locator(".result-panel")).toContainText("本次核对1片");
  await expect(page.locator(".result-panel")).not.toContainText("本次核对100片");
  await page.locator(".assistant-message").first().click();
  await expect(page.locator(".result-panel")).toContainText("历史回答对应结果（非本次请求）");
  await expect(page.locator(".result-panel")).toContainText("本次核对100片");
  await page.locator(".assistant-message").nth(2).click();
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
  await page.locator(".assistant-message").last().click();
  await expect(page.locator(".result-panel")).toContainText("本次回答对应结果");
  await expect(page.locator(".result-panel")).toContainText("本次核对1片");
});

test("评审推演必须主动选择，场景和历史不污染企业入口", async ({ page }) => {
  let requests = 0;
  const scenario = "review_real_bom_simulation";
  await page.route("**/api/v1/agent/sessions", r => {
    expect(r.request().postDataJSON().scenario_id).toBe(scenario);
    return r.fulfill({ json: { ...session,session_id:"review-session",scenario_id:scenario } });
  });
  await page.route("**/api/v1/agent/query", r => {
    requests++;
    const body=r.request().postDataJSON();
    expect(body.scenario_id).toBe(scenario);
    const result=reply(50);
    const data=result.structured_data!.data as any;
    data.quantity_check_status="sufficient";
    data.inventory_sufficient_for_requested=true;
    data.source_summary.review_scenario={synthetic:true,scenario_id:scenario};
    return r.fulfill({json:{...result,session_id:"review-session",scenario_id:scenario}});
  });
  await page.goto("/#/workspace");
  await expect(page.locator("#data-space")).toHaveValue("");
  expect(requests).toBe(0);
  await expect(page.locator(`#data-space option[value="${scenario}"]`)).toHaveCount(0);
  // Exercise archived pointer compatibility through the test harness, not a removed user entry.
  await page.evaluate(async (value) => {
    const path = "/src/composables/useAgent.ts";
    const module = await import(/* @vite-ignore */ path);
    await module.useAgent().chooseDataSpace(value);
  }, scenario);
  await page.getByLabel("输入分析问题").fill("生产50片可以吗");
  await page.getByRole("button",{name:"发送问题",exact:true}).click();
  await expect(page.locator(".result-panel")).toContainText("数量模拟核对（演示库存）");
  await expect(page.locator(".mode-banner")).toContainText("采用演示库存");
  await page.getByRole("button",{name:"新建分析",exact:true}).click();
  await expect(page.locator("#data-space")).toHaveValue("");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
});
