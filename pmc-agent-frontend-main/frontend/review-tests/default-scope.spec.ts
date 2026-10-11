import { test, expect, type Page } from "@playwright/test";
test.use({ httpCredentials: {username: process.env.PMC_E2E_USER_B ?? "review-b", password: process.env.PMC_E2E_PASSWORD_B ?? process.env.PMC_E2E_PASSWORD!} });

async function ask(page: Page, message: string, quick = false) {
  const finished = page.waitForResponse(r => r.url().endsWith("/api/v1/agent/query") && r.request().method() === "POST");
  if (quick) {
    await page.getByRole("button", {name:"展开推荐问题", exact:true}).click();
    await page.locator(".quick-questions").getByRole("button", {name:"查看BOM", exact:true}).click();
  } else {
    await page.getByLabel("输入分析问题").fill(message);
    await page.getByRole("button", {name:"发送问题", exact:true}).click();
  }
  const response = await finished;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(JSON.stringify(result)).not.toMatch(/content_sha256|source_uri|confirmed_by|[CE]:[\\/]|\.xlsx|\.xls\b/);
  await test.info().attach(`query-${test.info().attachments.length + 1}`, {
    body: Buffer.from(JSON.stringify({message, http_status: response.status(), response: result}, null, 2)),
    contentType: "application/json",
  });
  await expect(page.locator("#analysis-result")).toHaveAttribute("aria-busy", "false");
  return result;
}

test("最新精简：默认生产、边界、复用、零数量与刷新", async ({page, request}) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("KQ-Z112");
  await expect(page.locator("#review-scope")).toHaveValue("slim");
  await expect(page.locator("#review-scope option:checked")).toContainText("标准分析范围");
  await expect(page.getByRole("button", {name:"展开推荐问题"})).toHaveAttribute("aria-expanded","false");
  const collapsed = (await page.locator(".smart-queries").boundingBox())!.height;
  await page.getByRole("button", {name:"展开推荐问题"}).click();
  expect((await page.locator(".smart-queries").boundingBox())!.height).toBeGreaterThan(collapsed);
  await page.getByRole("button", {name:"收起",exact:true}).click();
  await expect(page.getByRole("note")).toContainText("34项BOM");
  await expect(page.getByRole("note")).toContainText("20261011T030952Z-b4f34740");
  await page.getByRole("button", {name:"产品物料目录", exact:true}).click();
  await expect(page.locator(".catalog-scroll tbody tr")).toHaveCount(34);
  const messages = ["查询KQ-Z112的BOM", "这个产品有多少项物料？", "最多能生产多少片？", "生产1件。",
    "那2件呢？", "为什么不能生产2片？", "最多可以生产多少？", "生产最大数量可以吗？", "再多生产1片呢？",
    "哪些物料限制产量？", "这些数量来自哪里？", "生产0片。", "那生产1个呢？", "生产50片", "生产100片"];
  let sid = "";
  for (const message of messages) {
    const response = await ask(page, message, message === messages[0]); sid = response.session_id;
    await expect(page.locator(".quick-questions")).toHaveCount(0);
    const data = response.structured_data.data;
    if (message === "生产0片。") {
      expect(response.status).toBe("invalid_query");
      expect(data).toBeNull();
      await expect(page.locator("#analysis-result")).not.toContainText("最大满足数量");
      continue;
    }
    expect(data.materials).toHaveLength(34);
    expect(data.theoretical_max_quantity).toBe(1);
    expect(data.dataset_version).toBe("20261011T030952Z-b4f34740");
    expect(data.synthetic).toBe(false);
    if (data.requested_quantity === 1) expect(data.inventory_sufficient_for_requested).toBe(true);
    if (data.requested_quantity === 2) {
      expect(data.inventory_sufficient_for_requested).toBe(false);
      expect(data.book_shortages.map((r:any)=>r.material_code).sort()).toEqual(["MAT-053","MAT-061"]);
      expect(data.book_shortages.every((r:any)=>Number(r.shortage_qty) === 1)).toBe(true);
    }
    await expect(page.locator("#analysis-result")).toContainText("34");
    await expect(page.locator("#analysis-result")).not.toContainText(/精简评审|保留\d+项|排除\d+项|没有合成补充|原66项/);
    expect(response.answer).not.toMatch(/精简评审|保留\d+项|排除\d+项|没有合成补充/);
    expect(response.provenance).toBeTruthy();
  }
  const history = await (await request.get(`/api/v1/agent/sessions/${sid}`)).json();
  expect(history.turns[11].fact_references).toEqual([]);
  expect(history.turns[5].response.structured_data.reused_from_turn_id).toBeTruthy();
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(messages.length);
  await expect(page.locator("#review-scope")).toHaveValue("slim");
  await expect(page.locator("#analysis-result")).toContainText("100");
  await expect(page.getByRole("button", {name:"展开推荐问题"})).toHaveAttribute("aria-expanded","false");
  await page.locator(".assistant-message").nth(3).click();
  await expect(page.locator("#analysis-result")).toContainText("满足生产1片");
  await expect(page.locator("#analysis-result")).toContainText("历史回答对应结果");
  await page.setViewportSize({width:390,height:844});
  await page.getByRole("button", {name:"展开推荐问题"}).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", {name:"收起",exact:true}).click();
  await page.setViewportSize({width:1440,height:1080});
  await page.screenshot({path:test.info().outputPath("standard-analysis.png"),fullPage:true});
});

test("最新精简：目录指南、完整切换、第二产品与Demo不串话", async ({page}) => {
  await page.goto("/");
  await expect(page.getByRole("button", {name:"展开推荐问题"})).toHaveAttribute("aria-expanded","false");
  for (const message of ["查询已发布BOM的产品。", "查询可以使用的产品", "有哪些产品？", "有哪些可以查询的BOM产品？", "给我看看产品目录。", "能查询哪些产品？"]) {
    const result = await ask(page, message);
    expect(result.structured_data.data.products.map((p:any)=>p.product_code)).toEqual(["KQ-Z112","KQ-BHX3588M","DEMO-PMC-01"]);
    await expect(page.locator("#analysis-result")).toContainText("演示产品");
  }
  expect((await ask(page,"有哪些Demo产品？")).structured_data.data.products).toHaveLength(1);
  expect((await ask(page,"只查看正式发布的企业BOM产品。")).structured_data.data.products).toHaveLength(2);
  expect((await ask(page,"只显示正式企业已发布BOM。")).structured_data.data.products).toHaveLength(2);
  expect((await ask(page,"切换到标准分析范围")).structured_data.data.materials).toHaveLength(34);
  expect((await ask(page,"查看KQ-Z112有哪些物料。")).structured_data.data.materials).toHaveLength(34);
  const directory = await ask(page,"看看库存。");
  const alias = directory.structured_data.data.materials[0].material_code;
  expect((await ask(page,`查询${alias}库存`)).structured_data.data.materials).toHaveLength(1);
  expect((await ask(page,"查询MAT-053库存")).structured_data.data.materials[0].material_code).toBe("MAT-053");
  expect((await ask(page,"查看KQ-Z112完整BOM。")).structured_data.data.line_count).toBe(66);
  await expect(page.locator("#review-scope")).toHaveValue("full");
  expect((await ask(page,"查询KQ-Z112完整物料。")).structured_data.data.line_count).toBe(66);
});

test("最新精简：切换指南、第二产品与Demo不串话", async ({page}) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("KQ-Z112");
  expect((await ask(page,"查看KQ-Z112完整BOM。")).structured_data.data.line_count).toBe(66);
  expect((await ask(page,"生产10片需要哪些物料？")).structured_data.data.materials).toHaveLength(66);
  expect((await ask(page,"查看对应库存。")).structured_data.data.matched_material_count).toBe(44);
  await page.locator("#review-product").selectOption("KQ-BHX3588M");
  expect((await ask(page,"查询这个产品的BOM。")).structured_data.data.line_count).toBe(91);
  expect((await ask(page,"生产10片需要哪些物料？")).structured_data.data.materials).toHaveLength(91);
  expect((await ask(page,"查看对应库存。")).structured_data.data.matched_material_count).toBe(58);
  expect((await ask(page,"查询DEMO-PMC-01。")).status).toBe("ok");
  expect((await ask(page,"最多生产多少台？")).structured_data.data.theoretical_max_quantity).toBe(75);
  await page.locator("#review-product").selectOption("KQ-Z112");
  await expect(page.locator("#review-scope")).toHaveValue("slim");
  expect((await ask(page,"生产1片可以吗？")).structured_data.data.inventory_sufficient_for_requested).toBe(true);
});

test("最新精简：Demo指南全部问题实际计算", async ({page}) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("DEMO-PMC-01");
  expect((await ask(page,"查询DEMO-PMC-01。")).structured_data.data.line_count).toBe(3);
  expect((await ask(page,"生产50台可以吗？")).structured_data.data.inventory_sufficient_for_requested).toBe(true);
  expect((await ask(page,"最多生产多少台？")).structured_data.data.theoretical_max_quantity).toBe(75);
  expect((await ask(page,"生产75台可以吗？")).structured_data.data.inventory_sufficient_for_requested).toBe(true);
  expect((await ask(page,"生产76台呢？")).structured_data.data.inventory_sufficient_for_requested).toBe(false);
  expect((await ask(page,"生产100台呢？")).structured_data.data.materials.filter((r:any)=>Number(r.shortage_qty)>0)).toHaveLength(4);
  expect((await ask(page,"为什么不能生产？")).provenance).toBeTruthy();
  expect((await ask(page,"针对缺料给出采购建议。")).structured_data.data.recommendations).toHaveLength(4);
  expect((await ask(page,"生产0台")).status).not.toBe("ok");
  expect((await ask(page,"生产1台")).structured_data.data.inventory_sufficient_for_requested).toBe(true);
});
