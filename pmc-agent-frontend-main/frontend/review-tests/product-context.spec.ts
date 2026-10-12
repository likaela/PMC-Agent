import { test, expect } from "@playwright/test";
test.use({
  httpCredentials: {
    username: process.env.PMC_E2E_USER_B ?? "review-b",
    password: process.env.PMC_E2E_PASSWORD_B!,
  },
});
test("产品上下文：同一对话16轮切换、证据、当前标识和刷新", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.locator(".active-product")).toContainText("未选择产品");
  const cases = [
    ["生产1片KQ-Z112。", "KQ-Z112", 1, true],
    ["那生产2片呢？", "KQ-Z112", 2, false],
    ["查询演示产品。", "DEMO-PMC-01", null, null],
    ["看看它的BOM。", "DEMO-PMC-01", null, null],
    ["生产50台可以吗？", "DEMO-PMC-01", 50, true],
    ["那生产100台呢？", "DEMO-PMC-01", 100, false],
    ["为什么不行？", "DEMO-PMC-01", 100, false],
    ["最多可以生产多少台？", "DEMO-PMC-01", null, null],
    ["回到KQ-Z112。", "KQ-Z112", null, null],
    ["生产1件。", "KQ-Z112", 1, true],
    ["查询BHX3588M。", "KQ-BHX3588M", null, null],
    ["生产10片呢？", "KQ-BHX3588M", 10, null],
    ["有哪些产品？", "KQ-BHX3588M", null, null],
    ["看看演示产品。", "DEMO-PMC-01", null, null],
    ["生产0台。", "DEMO-PMC-01", null, null],
    ["那生产75台呢？", "DEMO-PMC-01", 75, true],
  ] as const;
  const sessionIds = new Set<string>();
  let priorDemoTurn = "";
  for (let i = 0; i < cases.length; i++) {
    const [message, product, quantity, sufficient] = cases[i];
    await page.getByLabel("输入分析问题").fill(message);
    const received = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const http = await received;
    expect(http.status()).toBe(200);
    const r = await http.json(),
      s = r.structured_data,
      d = s.data ?? s.reused_result?.data ?? null;
    sessionIds.add(r.session_id);
    expect(r.review_product).toBe(product);
    expect(s.product_context.product_code).toBe(product);
    await expect(page.locator("#active-product-select")).toHaveValue(product);
    await expect(page.locator("#analysis-result")).toHaveAttribute(
      "aria-busy",
      "false",
    );
    await expect(page.locator(".assistant-message")).toHaveCount(i + 1);
    if (quantity !== null) {
      expect(d.requested_quantity).toBe(quantity);
      if (sufficient !== null)
        expect(d.inventory_sufficient_for_requested).toBe(sufficient);
    }
    if (i === 5) priorDemoTurn = r.turn_id;
    if (i === 6) expect(s.reused_from_turn_id).toBe(priorDemoTurn);
    if (i === 7) {
      expect(d.theoretical_max_quantity).toBe(75);
      await expect(page.locator("#analysis-result")).toContainText(
        "理论最大生产数量",
      );
    } else if (i !== 14) {
      await expect(
        page
          .locator("#analysis-result")
          .getByText(/^(最大满足数量|理论最大生产数量)$/),
      ).toHaveCount(0);
    }
    if (i === 3) expect(d.line_count).toBe(3);
    if (i === 9) {
      expect(d.materials).toHaveLength(34);
      expect(r.review_mode).toBe("current");
    }
    if (i === 12)
      expect(d.products.map((p: any) => p.product_code)).toEqual([
        "KQ-Z112",
        "KQ-BHX3588M",
        "DEMO-PMC-01",
      ]);
    if (i === 14) {
      expect(r.status).toBe("needs_input");
      expect(d).toBeNull();
    }
    await test.info().attach("turn-" + (i + 1), {
      body: Buffer.from(JSON.stringify({ message, response: r })),
      contentType: "application/json",
    });
  }
  for (const id of sessionIds) {
    const h = await request.get(`/api/v1/agent/sessions/${id}`);
    expect(h.status()).toBe(200);
    const saved = await h.json();
    expect(
      saved.turns.every(
        (t: any) =>
          t.response.structured_data.product_context.product_code ===
          saved.review_product,
      ),
    ).toBe(true);
  }
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
  await expect(page.locator("#analysis-result")).toContainText(
    "此回答属于KQ-Z112",
  );
  await page
    .getByRole("button", { name: "继续分析此产品", exact: true })
    .click();
  await expect(page.locator("#active-product-select")).toHaveValue("KQ-Z112");
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(16);
  await expect(page.locator("#active-product-select")).toHaveValue("KQ-Z112");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".active-product")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: test.info().outputPath("product-context.png"),
    fullPage: true,
  });
});

test("产品上下文：空白目录恢复与明确目录序号切换", async ({ page }) => {
  await page.goto("/");
  const ask = async (message: string) => {
    await page.getByLabel("输入分析问题").fill(message);
    const received = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const response = await received;
    expect(response.status()).toBe(200);
    return response.json();
  };
  const directory = await ask("只查看企业正式已发布BOM的产品");
  expect(
    directory.structured_data.data.products.map((p: any) => p.product_code),
  ).toEqual(["KQ-Z112", "KQ-BHX3588M"]);
  await expect(page.locator(".active-product")).toContainText("未选择产品");
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  await expect(page.locator(".active-product")).toContainText("未选择产品");
  const switched = await ask("切换到第一个产品");
  expect(switched.review_product).toBe("KQ-Z112");
  expect(switched.structured_data.query_type).toBe("product_overview");
  await expect(page.locator("#active-product-select")).toHaveValue("KQ-Z112");
  expect(
    (await ask("生产1片")).structured_data.data
      .inventory_sufficient_for_requested,
  ).toBe(true);
});

test("产品上下文：迟到响应不能覆盖新产品及刷新历史", async ({ page }) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("KQ-Z112");
  let release!: () => void, processed!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    ready = new Promise<void>((resolve) => {
      processed = resolve;
    });
  await page.route("**/api/v1/agent/query", async (route) => {
    if (route.request().postDataJSON().message !== "生产1片") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const r = await response.json();
    expect(r.review_product).toBe("KQ-Z112");
    expect(r.structured_data.data.requested_quantity).toBe(1);
    processed();
    await gate;
    try {
      await route.fulfill({ response });
    } catch {
      /* Browser deliberately cancelled the old response. */
    }
  });
  await page.getByLabel("输入分析问题").fill("生产1片");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await ready;
  await page.locator("#active-product-select").selectOption("DEMO-PMC-01");
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
  const query = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/agent/query") &&
      r.request().postDataJSON().message === "看看它的BOM",
  );
  await page.getByLabel("输入分析问题").fill("看看它的BOM");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  const r = await (await query).json();
  expect(r.structured_data.data.line_count).toBe(3);
  release();
  await expect(page.locator("#analysis-result")).toContainText("DEMO-PMC-01");
  await expect(page.locator("#analysis-result")).not.toContainText("MAT-053");
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(2);
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("#analysis-result")).toContainText(
    "此回答属于KQ-Z112",
  );
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
});

test("产品上下文：相对数量必须有当前产品的明确基数", async ({ page }) => {
  await page.goto("/");
  await page.locator("#review-product").selectOption("DEMO-PMC-01");
  const ask = async (message: string) => {
    await page.getByLabel("输入分析问题").fill(message);
    const received = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const response = await received;
    expect(response.status()).toBe(200);
    return response.json();
  };
  const unknown = await ask("再多生产1台呢");
  expect(unknown.status).toBe("needs_input");
  expect(unknown.structured_data.completed_steps).toEqual([]);
  await expect(page.locator("#active-product-select")).toHaveValue(
    "DEMO-PMC-01",
  );
  expect((await ask("生产50台")).structured_data.data.requested_quantity).toBe(
    50,
  );
  const next = await ask("再多生产1台呢");
  expect(next.structured_data.data.requested_quantity).toBe(51);
  expect(next.structured_data.data.inventory_sufficient_for_requested).toBe(
    true,
  );
  await expect(page.locator("#analysis-result")).toContainText("生产51");
});
