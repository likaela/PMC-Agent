import { test, expect } from "@playwright/test";
test("正式开发工作台实际HTTP：当前34项、1/2边界、版本恢复、34/91/75切换", async ({
  page,
}) => {
  await page.goto("/#/workspace");
  await expect(
    page.getByRole("button", { name: "展开推荐问题", exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "展开推荐问题", exact: true }).click();
  await expect(page.locator(".quick-questions button")).not.toHaveCount(0);
  await page.getByRole("button", { name: "收起", exact: true }).click();
  await expect(page.locator(".quick-questions")).toHaveCount(0);
  await expect(page.locator("#local-review-product option")).toHaveCount(4);
  await page.locator("#local-review-product").selectOption("KQ-Z112");
  await expect(page.locator("#local-review-scope")).toHaveCount(0);
  async function ask(text: string) {
    const finished = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByLabel("输入分析问题").fill(text);
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const response = await finished;
    expect(response.status()).toBe(200);
    const value = await response.json();
    await expect(page.locator("#analysis-result")).toHaveAttribute(
      "aria-busy",
      "false",
    );
    return value;
  }
  const first = await ask("生产1件。");
  expect(first.structured_data.data.materials).toHaveLength(34);
  expect(first.structured_data.data.inventory_sufficient_for_requested).toBe(
    true,
  );
  expect(first.structured_data.data.theoretical_max_quantity).toBe(1);
  await expect(page.locator("#analysis-result")).toContainText("满足生产1片");
  const two = await ask("生产2件呢？");
  expect(two.structured_data.data.inventory_sufficient_for_requested).toBe(
    false,
  );
  expect(
    two.structured_data.data.book_shortages
      .map((r: any) => r.material_code)
      .sort(),
  ).toEqual(["MAT-053", "MAT-061"]);
  await expect(page.locator("#analysis-result")).toContainText(
    "不能满足生产2片",
  );
  expect(
    (await ask("最多可以生产多少片？")).structured_data.data
      .theoretical_max_quantity,
  ).toBe(1);
  expect((await ask("生产0片。")).status).toBe("invalid_query");
  expect(
    (await ask("那生产1个呢？")).structured_data.data.requested_quantity,
  ).toBe(1);
  await page.reload();
  await expect(page.locator("#local-review-scope")).toHaveCount(0);
  await expect(page.locator(".assistant-message")).toHaveCount(5);
  await expect(page.locator("#analysis-result")).toContainText("V01-C34");
  await expect(
    page.getByRole("button", { name: "展开推荐问题", exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  await page.locator(".assistant-message").nth(1).click();
  await expect(page.locator("#analysis-result")).toContainText(
    "历史回答对应结果",
  );
  await expect(page.locator("#analysis-result")).toContainText(
    "不能满足生产2片",
  );
  const catalog = await ask("查询已发布BOM的产品");
  expect(catalog.structured_data.data.products).toHaveLength(3);
  await expect(page.locator("#local-review-scope")).toHaveCount(0);
  expect(
    (await ask("查询KQ-Z112完整物料")).structured_data.data.line_count,
  ).toBe(34);
  await page.locator("#local-review-product").selectOption("KQ-BHX3588M");
  expect(
    (await ask("查询KQ-BHX3588M的BOM")).structured_data.data.line_count,
  ).toBe(91);
  await page.locator("#local-review-product").selectOption("DEMO-PMC-01");
  expect(
    (await ask("最多能生产多少台")).structured_data.data
      .theoretical_max_quantity,
  ).toBe(75);
  await page.locator("#local-review-product").selectOption("KQ-Z112");
  expect(
    (await ask("生产1片可以吗")).structured_data.data.materials,
  ).toHaveLength(34);
  await expect(page.locator("#data-space")).toHaveCount(0);
  await page.locator("#local-review-product").selectOption("KQ-Z112");
  const realAgain = await ask("生产1片可以吗");
  expect(realAgain.structured_data.data.synthetic).toBe(false);
  expect(realAgain.structured_data.data.theoretical_max_quantity).toBe(1);
});

test("本地入口：别称切换、原始消息、子料查询和多产品刷新", async ({
  page,
  request,
}) => {
  await page.goto("/#/workspace");
  async function ask(message: string) {
    const wait = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByLabel("输入分析问题").fill(message);
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const http = await wait;
    expect(http.status()).toBe(200);
    return http.json();
  }
  expect(
    (await ask("生产1片KQ-Z112")).structured_data.data.materials,
  ).toHaveLength(34);
  const overview = await ask("查询演示产品");
  expect(overview.structured_data.query_type).toBe("product_overview");
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
  expect((await ask("看看它的BOM")).structured_data.data.line_count).toBe(3);
  expect(
    (await ask("生产50台可以吗")).structured_data.data
      .inventory_sufficient_for_requested,
  ).toBe(true);
  await ask("回到KQ-Z112");
  expect((await ask("生产1件")).structured_data.data.requested_quantity).toBe(
    1,
  );
  await ask("查询BHX3588M");
  const bom = await ask("看看它的BOM");
  expect(bom.structured_data.data.line_count).toBe(91);
  const child = bom.structured_data.data.lines[0].child_item.material_code;
  const stock = await ask(`查询${child}库存`);
  await expect(page.locator("#active-product-select")).toHaveValue(
    "KQ-BHX3588M",
  );
  const saved = await (
    await request.get(
      (process.env.PMC_WORKSTATION_API_URL ?? "http://127.0.0.1:8000") +
        `/api/v1/agent/sessions/${stock.session_id}`,
    )
  ).json();
  expect(saved.product_context.product_code).toBe("KQ-BHX3588M");
  expect(saved.turns[0].user_query).toBe("查询BHX3588M");
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(9);
  await expect(page.locator("#active-product-select")).toHaveValue(
    "KQ-BHX3588M",
  );
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("#active-product-select")).toHaveValue(
    "KQ-BHX3588M",
  );
  await expect(page.locator("#analysis-result")).toContainText(
    "此回答属于KQ-Z112",
  );
});
