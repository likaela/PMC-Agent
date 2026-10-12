import { test, expect } from "@playwright/test";

// These legacy pointer cases intentionally exercise a server without a catalog.
// Do not let a separately running enterprise backend alter their storage scope.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/agent/catalog", route => route.fulfill({ status: 404, json: {} }));
});
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";
import { sessionKey } from "../src/services/sessionStorage";

function reply(synthetic: boolean, quantity: number | null) {
  return envelope("production_capacity", {
    calculation_scope:"excel_book_observation", quantity_review:true, slim_review:true,
    product:"EXAMPLE-A", scenario_product_code:"EXAMPLE-REVIEW-SLIM", revision:"V01", product_unit:"片",
    scenario_name:synthetic ? "精简评审推演（合成补充库存）" : "精简可核验物料评审模型",
    synthetic, original_material_count:66, total_material_count:2, matched_material_count:2,
    comparable_material_count:quantity == null ? 0 : 2, requested_quantity:quantity,
    theoretical_max_quantity:synthetic ? 50 : 0, inventory_sufficient_for_requested:quantity == null ? null : synthetic && quantity <= 50,
    quantity_check_status:quantity == null ? null : synthetic && quantity <= 50 ? "sufficient" : "insufficient",
    source_summary:{review_scenario:{filtered:true,synthetic},unit_confirmation:{unit:"片"}},
    materials:[{material_code:"EXAMPLE-M1",name:"测试物料",qty_per:"2.00",required_qty:quantity == null ? null : String(quantity*2),
      recorded_stock_qty:synthetic ? "100.00" : "0.00",actual_stock_qty:synthetic ? "100.00" : "0.00",available_qty:null,
      book_shortage_qty:quantity == null ? null : synthetic && quantity <= 50 ? "0.00" : "2.00",
      comparison_status:"comparable",quantity_status:synthetic && quantity != null && quantity <= 50 ? "sufficient" : "shortage",
      unit:"片",inventory_unit:"片",record_found:true,record_count:1,details:[]}],
  },{answer:quantity == null ? "本模型最多50片" : `本模型${quantity}片数量核对`});
}

test("精简模型只展示后端范围、最大满足量和单耗，未知库存不补零",()=>{
  const r=reply(false,1),original=JSON.stringify(r);
  const vm=adaptBackendResponse(r,"最多能生产多少片？");
  expect(vm.slimReview).toBe(true);
  expect(vm.metrics?.find(m=>m.label==="最大满足数量")?.value).toBe("0片");
  expect(vm.answer).not.toContain("50片"); // Old prose cannot override returned maximum=0.
  expect(vm.materials[0].recordedStock).toBe("0.00");
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[0].qtyPer).toBe("2.00");
  expect(vm.metrics?.some(m=>/时点|预留|待核/.test(m.label))).toBe(false);
  expect(JSON.stringify(r)).toBe(original);
});

test("新版范围、脱敏编号和真实后端最大值不沿用40或50", () => {
  const r = reply(false, 7);
  const data = r.structured_data!.data as any;
  Object.assign(data, { total_material_count: 34, excluded_material_count: 32,
    dataset_version: "synthetic-version-new", theoretical_max_quantity: 7,
    inventory_sufficient_for_requested: true, quantity_check_status: "sufficient" });
  data.materials[0].material_code = "MAT-001";
  data.materials[0].name = "评审物料001";
  data.materials[0].recorded_stock_qty = "14.00";
  data.materials[0].quantity_status = "sufficient";
  const vm = adaptBackendResponse(r,"最多能生产多少片？");
  expect(vm.metrics?.find(m => m.label === "物料数量")?.value).toBe("34");
  expect(vm.metrics?.some(m => /保留|排除|原完整/.test(m.label))).toBe(false);
  expect(data.excluded_material_count).toBe(32); // Audit data is preserved, not falsified.
  expect(vm.metrics?.find(m => m.label === "数据集版本")?.value).toBe("synthetic-version-new");
  expect(vm.metrics?.find(m => m.label === "最大满足数量")?.value).toBe("7片");
  expect(vm.answer).toContain("当前分析范围：34项物料");
  expect(vm.materials[0].name).toBe("物料001");
  expect(vm.materials[0].code).toBe("MAT-001");
  expect(vm.materials[0].recordedStock).toBe("14.00");
  expect(vm.materials[0].available).toBeNull();
});

test("旧版精简会话失效时不展示旧物料，新分析绑定新版", async ({page}) => {
  const scenario = "kq_z112_review_slim";
  await page.addInitScript(({key, scenario}) => sessionStorage.setItem(key, JSON.stringify({session_id:"old-slim",scenario_id:scenario})),
    {key:sessionKey("http://127.0.0.1:8000",scenario),scenario});
  await page.route("**/api/v1/agent/sessions/old-slim?*", r => r.fulfill({status:404,json:{code:"SESSION_NOT_FOUND",user_message:"会话已失效"}}));
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({json:{...session,session_id:"new-slim",scenario_id:scenario,context:{dataset_version:"new-version"}}}));
  await page.route("**/api/v1/agent/query", r => {
    expect(r.request().postDataJSON().session_id).toBe("new-slim");
    const response={...reply(false,1),scenario_id:scenario,session_id:"new-slim",turn_id:"new-turn"};
    (response.structured_data!.data as any).dataset_version="new-version";
    return r.fulfill({json:response});
  });
  await page.goto("/#/workspace");
  await expect(page.locator(`#data-space option[value="${scenario}"]`)).toHaveCount(0);
  // Exercise archived pointer compatibility through the test harness, not a removed user entry.
  await page.evaluate(async (value) => {
    const path = "/src/composables/useAgent.ts";
    const module = await import(/* @vite-ignore */ path);
    await module.useAgent().chooseDataSpace(value);
  }, scenario);
  await expect(page.getByText(/当前会话属于旧数据版本/)).toBeVisible();
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
  await page.getByLabel("输入分析问题").fill("生产1片可以吗");
  await page.getByRole("button",{name:"发送问题",exact:true}).click();
  await expect(page.locator("#analysis-result")).toContainText("new-version");
});

test("精简场景显式选择、边界结果、刷新与历史恢复不污染企业",async({page})=>{
  const scenario="kq_z112_review_slim_synthetic",turns:any[]=[];
  await page.route("**/api/v1/agent/sessions",r=>{
    expect(r.request().postDataJSON().scenario_id).toBe(scenario);
    return r.fulfill({json:{...session,session_id:"slim-session",scenario_id:scenario}});
  });
  await page.route("**/api/v1/agent/sessions/slim-session?*",r=>r.fulfill({json:{...session,session_id:"slim-session",scenario_id:scenario,turns}}));
  await page.route("**/api/v1/agent/query",r=>{
    expect(r.request().postDataJSON().scenario_id).toBe(scenario);
    const q=r.request().postDataJSON().message;
    const response={...reply(true,q.includes("51")?51:50),scenario_id:scenario,session_id:"slim-session",turn_id:`slim-${turns.length}`};
    turns.push({turn_id:response.turn_id,sequence_no:turns.length+1,user_query:q,response,created_at:session.created_at});
    return r.fulfill({json:response});
  });
  await page.goto("/#/workspace");
  await expect(page.locator("#data-space")).toHaveValue("");
  await expect(page.locator(`#data-space option[value="${scenario}"]`)).toHaveCount(0);
  // Exercise archived pointer compatibility through the test harness, not a removed user entry.
  await page.evaluate(async (value) => {
    const path = "/src/composables/useAgent.ts";
    const module = await import(/* @vite-ignore */ path);
    await module.useAgent().chooseDataSpace(value);
  }, scenario);
  for(const n of [50,51]){
    await page.getByLabel("输入分析问题").fill(`生产${n}片`);
    await page.getByRole("button",{name:"发送问题",exact:true}).click();
    await expect(page.locator("#analysis-result")).toContainText(`生产${n}片对应的物料需求`);
    await expect(page.locator(".materials-card")).toContainText("BOM单耗");
    await expect(page.locator("#analysis-result")).not.toContainText("最大满足数量");
    await expect(page.locator(".mode-banner")).toContainText("演示库存");
    await expect(page.locator("#analysis-result")).not.toContainText("精简评审");
  }
  await page.reload();
  await expect(page.locator("#data-space")).toHaveValue("");
  await expect(page.locator(`#data-space option[value="${scenario}"]`)).toHaveCount(0);
  // Exercise archived pointer compatibility through the test harness, not a removed user entry.
  await page.evaluate(async (value) => {
    const path = "/src/composables/useAgent.ts";
    const module = await import(/* @vite-ignore */ path);
    await module.useAgent().chooseDataSpace(value);
  }, scenario);
  await expect(page.locator("#analysis-result")).toContainText("生产51片对应的物料需求");
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("#analysis-result")).toContainText("生产50片对应的物料需求");
  await expect(page.locator("#analysis-result")).toContainText("历史回答对应结果");
  await page.locator("#data-space").selectOption("");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
});
