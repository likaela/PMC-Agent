import { test, expect, type APIRequestContext } from "@playwright/test";
const baseURL = "http://127.0.0.1:8090";
const products = [["KQ-Z112", 34, 34], ["KQ-BHX3588M", 91, 58]] as const;

test("BHX数量专项：正式浏览器九轮、真实Tool证据、无空卡及刷新恢复", async ({page, request}) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("KQ-BHX3588M");
  let sid = "", capacityTurn = "", productionTurn = "";
  const messages = ["查询KQ-BHX3588M的BOM。", "看看库存。", "最多可以生产多少片？", "哪些物料限制数量？", "生产1片可以吗？", "生产10片呢？", "为什么不足？", "生产100片呢？", "查看来源。"];
  for (const [i, message] of messages.entries()) {
    await page.getByLabel("输入分析问题").fill(message);
    const received = page.waitForResponse(r => r.url().endsWith("/api/v1/agent/query") && r.request().method() === "POST");
    await page.getByRole("button", {name:"发送问题",exact:true}).click();
    const http = await received;
    expect(http.status()).toBe(200);
    const r = await http.json(), s = r.structured_data, d = s.data;
    sid = r.session_id;
    expect(r.review_product).toBe("KQ-BHX3588M");
    await expect(page.locator("#analysis-result")).toHaveAttribute("aria-busy","false");
    await expect(page.locator("#analysis-result")).not.toContainText(/未提供|权威可用库存|快照时间待确认|库存变动|不会采用|需要补充查询信息/);
    expect((await page.locator("#analysis-result .purchase-grid strong").allTextContents()).join(" ")).not.toMatch(/未提供|未知/);
    if (i === 0) { expect(d.line_count).toBe(91); await expect(page.locator(".materials-card tbody tr")).toHaveCount(91); }
    if (i === 1) expect(d.matched_material_count).toBe(58);
    if (i === 2) {
      capacityTurn = r.turn_id;
      expect(s.completed_steps).toEqual([{operation:"enterprise_book_capacity_query",status:"ok"}]);
      expect(d.verified_material_count).toBe(55);
      expect(d.verified_material_capacity).toBe(0);
      expect(d.theoretical_max_quantity).toBe(0);
      expect(d.full_bom_capacity_determined).toBe(true);
      expect(d.limiting_materials).toHaveLength(7);
      expect(d.limiting_materials.every((m:any) => Number(m.stock_qty) === 0 && Number(m.qty_per)>0)).toBe(true);
      await expect(page.locator("#analysis-result")).toContainText("已核算物料产量上限");
      await expect(page.locator("#analysis-result")).not.toContainText("生产数量");
    }
    if (i === 3) expect(s.reused_from_turn_id).toBe(capacityTurn);
    if ([4,5,7].includes(i)) {
      const n = i === 4 ? 1 : i === 5 ? 10 : 100;
      expect(d.requested_quantity).toBe(n);
      expect(d.materials).toHaveLength(91);
      expect(d.comparable_material_count).toBe(55);
      expect(d.book_shortages).toHaveLength(i === 4 ? 7 : i === 5 ? 18 : 36);
      expect(d.inventory_sufficient_for_requested).toBe(false);
      expect(d.materials.filter((m:any) => !m.record_found).every((m:any) => m.recorded_stock_qty === null && m.shortage_qty === null)).toBe(true);
      await expect(page.locator("#analysis-result .purchase-grid")).not.toContainText("产量上限");
      productionTurn = r.turn_id;
    }
    if (i === 6) expect(s.reused_from_turn_id).toBe(productionTurn);
    if (i === 8) { expect(r.provenance).toBeTruthy(); await expect(page.locator("#analysis-result .purchase-grid")).toHaveCount(0); }
    await test.info().attach(`bhx-${i+1}`,{body:Buffer.from(JSON.stringify({message,response:r})),contentType:"application/json"});
  }
  const history = await (await request.get(`/api/v1/agent/sessions/${sid}`)).json();
  expect(history.turns[2].fact_references[0].tool_name).toBe("enterprise_book_capacity_query");
  expect(history.turns[2].fact_references[0].result.data.verified_material_count).toBe(55);
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(9);
  await expect(page.locator("#analysis-result")).toContainText("本次查询来源");
  await page.locator(".assistant-message").nth(2).click();
  await expect(page.locator("#analysis-result")).toContainText("历史回答对应结果");
  await expect(page.locator("#analysis-result")).toContainText("已核算物料产量上限");
  await page.screenshot({path:test.info().outputPath("bhx-capacity.png"),fullPage:true});
});

test("全局展示：跨产品生产与最大量不串用，历史按原问题恢复", async ({page}) => {
  await page.goto("/");
  for (const [message, product, n, max] of [
    ["KQ-Z112生产1片。","KQ-Z112",1,null],
    ["KQ-BHX3588M最多可以生产多少片？","KQ-BHX3588M",null,0],
    ["演示产品生产50台。","DEMO-PMC-01",50,null],
    ["KQ-BHX3588M生产100片。","KQ-BHX3588M",100,null],
    ["有哪些已发布产品？","KQ-BHX3588M",null,null],
  ] as const) {
    await page.getByLabel("输入分析问题").fill(message);
    const received = page.waitForResponse(r => r.url().endsWith("/api/v1/agent/query") && r.request().method() === "POST");
    await page.getByRole("button",{name:"发送问题",exact:true}).click();
    const http = await received, r = await http.json(), d = r.structured_data.data;
    expect(http.status()).toBe(200);
    expect(r.review_product).toBe(product);
    await expect(page.locator("#analysis-result")).toHaveAttribute("aria-busy","false");
    if (n !== null) expect(d.requested_quantity).toBe(n);
    if (max !== null) expect(d.verified_material_capacity).toBe(max);
    else await expect(page.locator("#analysis-result").getByText(/^(最大满足数量|理论最大生产数量|已核算物料产量上限)$/)).toHaveCount(0);
    if (d.products) expect(d.products.map((p:any)=>p.product_code)).toEqual(["KQ-Z112","KQ-BHX3588M","DEMO-PMC-01"]);
    await expect(page.locator("#active-product-select")).toHaveValue(product);
  }
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(5);
  await expect(page.locator("#analysis-result")).toContainText("可查询产品目录");
});
async function create(request: APIRequestContext, product_code: string) {
  const response = await request.post("/api/v1/agent/sessions", { data: { product_code } });
  expect(response.status()).toBe(200);
  return (await response.json()).session_id as string;
}
async function query(request: APIRequestContext, session_id: string, message: string) {
  const response = await request.post("/api/v1/agent/query", { data: { session_id, message, persist_session: true } });
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(JSON.stringify(result)).not.toMatch(/content_sha256|evidence_sha256|source_uri|confirmed_by|[CE]:[\\/]|\.xlsx|\.xls\b|\b[a-f0-9]{64}\b/i);
  return result;
}

test("真实HTTP：完整两产品BOM及任意数量、已知库存差额、未知不补零", async ({ request }) => {
  const catalog = await request.get("/api/v1/review/catalog");
  expect((await catalog.json()).products.map((p: any) => p.product_code)).toEqual(["KQ-Z112", "KQ-BHX3588M", "DEMO-PMC-01"]);
  for (const [product, count, matched] of products) {
    const sid = await create(request, product);
    const bom = await query(request, sid, `查询${product}的BOM`);
    expect(bom.structured_data.data.line_count).toBe(count);
    expect(bom.structured_data.data.parent_item.material_code).toBe(product);
    expect((await (await request.get(`/api/v1/review/products/${product}/materials`)).json()).materials).toHaveLength(count);
    const stock = await query(request, sid, `查询${product}的库存`);
    expect(stock.structured_data.data.matched_material_count).toBe(matched);
    for (const quantity of [1, 2, 10, 50, 100, 137]) {
      const result = await query(request, sid, `生产${quantity}片可以吗`);
      const data = result.structured_data.data;
      expect(data.requested_quantity).toBe(quantity);
      expect(data.materials).toHaveLength(count);
      expect(data.matched_material_count).toBe(matched);
      expect(data.formal_production_approved).toBe(false);
      for (const row of data.materials) {
        expect(Number(row.required_qty)).toBeCloseTo(Number(row.qty_per) * quantity, 8);
        if (row.actual_stock_qty === null) expect(row.shortage_qty).toBeNull();
        else expect(Number(row.shortage_qty)).toBeCloseTo(Math.max(Number(row.required_qty) - Number(row.actual_stock_qty), 0), 8);
      }
    }
    const reason = await query(request, sid, "为什么不能生产？");
    expect(reason.structured_data.data.requested_quantity).toBe(137);
    expect(reason.structured_data.data.materials).toHaveLength(count);
    expect(reason.provenance).toBeTruthy();
    const zero = await query(request, sid, "生产0片");
    expect(zero.status).toBe("invalid_query");
    expect(zero.structured_data.data).toBeFalsy();
    expect((await query(request, sid, "那生产1个呢")).structured_data.data.requested_quantity).toBe(1);
    const history = await (await request.get(`/api/v1/agent/sessions/${sid}`)).json();
    expect(history.turns).toHaveLength(11);
    expect(history.turns.at(-2).fact_references).toEqual([]);
    expect(history.context.production.quantity).toBe(1);
  }
});

test("实际Caddy身份、两账号隔离、Demo限定权限、私有路由拒绝", async ({ playwright, request }) => {
  const b = await playwright.request.newContext({ baseURL, httpCredentials: { username: process.env.PMC_E2E_USER_B ?? "review-b", password: process.env.PMC_E2E_PASSWORD_B ?? process.env.PMC_E2E_PASSWORD! } });
  const guest = await playwright.request.newContext({ baseURL, httpCredentials: { username: process.env.PMC_E2E_USER_C ?? "demo-only", password: process.env.PMC_E2E_PASSWORD_C ?? process.env.PMC_E2E_PASSWORD! } });
  const anon = await playwright.request.newContext({ baseURL, httpCredentials: { username: "", password: "" } });
  try {
    const sid = await create(request, "KQ-Z112");
    await query(request, sid, "生产1片");
    expect((await anon.get("/api/v1/review/catalog")).status()).toBe(401);
    expect((await b.get(`/api/v1/agent/sessions/${sid}`)).status()).toBe(404);
    expect((await b.post("/api/v1/agent/query", { data: { session_id: sid, message: "继续" } })).status()).toBe(404);
    expect((await b.get(`/api/v1/agent/sessions/${sid}`, { headers: { "X-PMC-User": "review-a", "X-PMC-Proxy-Key": process.env.PMC_REVIEW_PROXY_SECRET! } })).status()).toBe(404);
    expect((await (await guest.get("/api/v1/review/catalog")).json()).products.map((p: any) => p.product_code)).toEqual(["DEMO-PMC-01"]);
    expect((await guest.post("/api/v1/agent/sessions", { data: { product_code: "KQ-Z112" } })).status()).toBe(404);
    expect((await guest.get("/api/v1/review/products/KQ-Z112/materials")).status()).toBe(404);
    for (const path of ["/api/v1/chat", "/api/v1/workflows", "/api/v1/facts", "/data/raw/a.xls", "/data/facts/pmc_facts.db", "/data/normalized/a.json", "/.env", "/.git/config", "/docs/private.md"])
      expect((await request.get(path)).status()).toBe(404);
    expect((await request.post("/api/v1/agent/query", { data: { session_id: sid, message: "继续", scenario_id: "kq_z112_review_slim" } })).status()).toBe(422);
    expect((await request.post("/api/v1/agent/query", { data: { session_id: sid, message: "查询KQ-BHX3588M的BOM" } })).status()).toBe(409);
    expect((await request.post("/api/v1/agent/query", { data: { session_id: sid, message: "生产1片", product_code: "KQ-BHX3588M" } })).status()).toBe(422);
  } finally { await b.dispose(); await guest.dispose(); await anon.dispose(); }
});

test("同一入口真实执行完整合成Demo 50/75/76/100及采购", async ({ request }) => {
  const sid = await create(request, "DEMO-PMC-01");
  for (const [quantity, ready] of [[50, true], [75, true], [76, false], [100, false]]) {
    const data = (await query(request, sid, `生产${quantity}台DEMO-PMC-01`)).structured_data.data;
    expect(data.theoretical_max_quantity).toBe(75);
    expect(data.inventory_sufficient_for_requested).toBe(ready);
  }
  const purchase = (await query(request, sid, "帮我生成采购建议")).structured_data.data;
  expect(purchase.recommendations).toHaveLength(4);
  expect(purchase.total_purchase_cost).toBe("1560.00");
});

test.describe("独立第二账号浏览器验收", () => {
test.use({ httpCredentials: { username: process.env.PMC_E2E_USER_B ?? "review-b", password: process.env.PMC_E2E_PASSWORD_B ?? process.env.PMC_E2E_PASSWORD! } });
test("生产正式页面：完整目录、数量跟随、零数量、产品切换及历史恢复", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#review-product option")).toHaveCount(4);
  expect(await page.locator("#review-product").inputValue()).toBe("");
  await page.locator("#review-product").selectOption("KQ-Z112");
  await expect(page.getByRole("note")).toContainText("34项BOM");
  await expect(page.locator("#review-scope")).toHaveCount(0);
  await expect(page.getByRole("note")).toContainText("34项BOM");
  await page.getByRole("button", { name: "产品物料目录", exact: true }).click();
  await expect(page.locator(".catalog-scroll tbody tr")).toHaveCount(34);
  async function ask(message: string) {
    const complete = page.waitForResponse(r => r.url().endsWith("/api/v1/agent/query") && r.request().method() === "POST");
    await page.getByLabel("输入分析问题").fill(message);
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const response = await complete;
    expect(response.status()).toBe(200);
    await expect(page.locator("#analysis-result")).not.toContainText("正在等待分析结果");
    return response.json();
  }
  expect((await ask("生产137片可以吗")).structured_data.data.requested_quantity).toBe(137);
  await expect(page.locator("#analysis-result")).toContainText("137");
  expect((await ask("生产0片")).status).toBe("invalid_query");
  await expect(page.locator("#analysis-result")).not.toContainText("已计算34项BOM需求");
  expect((await ask("那生产1个呢")).structured_data.data.requested_quantity).toBe(1);
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(3);
  await expect(page.getByRole("note")).toContainText("KQ-Z112");
  await expect(page.locator("#analysis-result")).toContainText("1片");
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("#analysis-result")).toContainText("历史回答对应结果");
  await expect(page.locator("#analysis-result")).toContainText("137");
  await page.locator("#review-product").selectOption("KQ-BHX3588M");
  await expect(page.locator(".assistant-message")).toHaveCount(3);
  await expect(page.locator("#analysis-result")).toContainText("让每个问题都有清晰的落点");
  await expect(page.getByRole("note")).toContainText("91项BOM");
  expect((await ask("生产10片需要哪些物料")).structured_data.data.materials).toHaveLength(91);
  await page.locator("#review-product").selectOption("KQ-Z112");
  await expect(page.locator("#review-scope")).toHaveCount(0);
  await expect(page.locator(".assistant-message")).toHaveCount(4);
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(0);
  await expect(page.locator("#analysis-result")).toContainText("让每个问题都有清晰的落点");
  // Explicit product in free text switches through the authenticated resolver, not a local catalog.
  expect((await ask("查询DEMO-PMC-01的BOM")).structured_data.data.parent_item.material_code).toBe("DEMO-PMC-01");
  await expect(page.getByRole("note")).toContainText("演示产品");
  expect((await ask("生产50台可以吗")).structured_data.data.inventory_sufficient_for_requested).toBe(true);
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(2);
  await expect(page.locator("#analysis-result")).toContainText("本次需求库存齐套");
});

test("正式页面请求失败不会伪造成功或恢复旧物料表", async ({ page }) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("KQ-Z112");
  await page.route("**/api/v1/agent/query", route => route.fulfill({ status: 500, body: "Private failure" }));
  await page.getByLabel("输入分析问题").fill("生产1片");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toContainText("分析服务暂时异常");
  await expect(page.locator("#analysis-result")).not.toContainText("Private failure");
  await expect(page.locator("#analysis-result")).not.toContainText("齐套");
  await page.unroute("**/api/v1/agent/query");
  await page.getByRole("button", { name: "重试原问题" }).click();
  await expect(page.locator("#analysis-result")).toContainText("满足生产1片");
  await expect(page.locator("#analysis-result .purchase-grid")).not.toContainText("最大满足数量");
  await page.route("**/api/v1/review/resolve", route => route.fulfill({ status: 404, body: "Private access denied" }));
  await page.getByLabel("输入分析问题").fill("查询未授权产品");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toContainText("产品不可访问");
  await expect(page.locator("#analysis-result")).not.toContainText("最大满足数量");
  await expect(page.locator("#analysis-result")).not.toContainText("Private access denied");
});
test("指南问题与受保护物料目录：真实追问、来源、未知产能不套用Demo", async ({ request }) => {
  for (const [product, count] of products) {
    const sid = await create(request, product);
    const directory = await (await request.get(`/api/v1/review/products/${product}/materials`)).json();
    const material = directory.materials[0].material_code;
    const stock = await query(request, sid, `查询${material}的库存`);
    expect(stock.provenance).toBeTruthy();
    expect((await query(request, sid, `查询${product}的BOM`)).structured_data.data.line_count).toBe(count);
    expect((await query(request, sid, "生产10片需要哪些物料")).structured_data.data.requested_quantity).toBe(10);
    expect((await query(request, sid, "生产100片呢")).structured_data.data.requested_quantity).toBe(100);
    for (const message of ["哪些物料数量不足", "这些数量来自哪里？", "为什么不能生产？"]) {
      const result = await query(request, sid, message);
      expect(result.structured_data.data.requested_quantity).toBe(100);
      expect(result.structured_data.data.materials).toHaveLength(count);
      expect(result.provenance).toBeTruthy();
    }
    const capacity = await query(request, sid, "2026年9月16日最多能生产多少片");
    if (product === "KQ-Z112") {
      expect(capacity.status).toBe("ok");
      expect(capacity.structured_data.data.theoretical_max_quantity).toBe(1);
    } else {
      expect(capacity.status).toBe("ok");
      expect(capacity.structured_data.data.verified_material_count).toBe(55);
      expect(capacity.structured_data.data.verified_material_capacity).toBe(0);
      expect(capacity.structured_data.data.theoretical_max_quantity).toBe(0);
      expect(capacity.structured_data.data.capacity_scope).toBe("verified_subset");
      expect(capacity.structured_data.data.full_bom_capacity_determined).toBe(true);
    }
  }
});
});
