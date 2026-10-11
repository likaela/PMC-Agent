import { test, expect } from "@playwright/test";

test("隔离合成Demo真实HTTP：BOM、理论上限、缺口与原因", async ({ playwright }) => {
  const client = await playwright.request.newContext({
    baseURL: "http://127.0.0.1:8080",
    httpCredentials: { username: "trial-a", password: process.env.PMC_E2E_PASSWORD! },
  });
  try {
    const created = await client.post("/api/v1/agent/sessions", { data: {} });
    expect(created.status()).toBe(200);
    const { session_id } = await created.json();
    async function query(message: string) {
      const response = await client.post("/api/v1/agent/query", {
        data: { message, session_id, scenario_id: "demo_scenario_50_vs_100", persist_session: true },
      });
      expect(response.status()).toBe(200);
      const result = await response.json();
      expect(result.status).toBe("ok");
      expect(JSON.stringify(result)).not.toContain("KQ-Z112");
      return result;
    }
    const bom = await query("查询DEMO-PMC-01的BOM");
    // Root has three relationships; its subassembly expands to four leaf materials.
    expect(bom.structured_data.data.line_count).toBe(3);
    const capacity = await query("DEMO-PMC-01最多能生产多少台");
    expect(capacity.structured_data.data.theoretical_max_quantity).toBe(75);
    const hundred = await query("生产100台DEMO-PMC-01");
    expect(hundred.structured_data.data.materials.filter((r: any) => r.is_ready === false)).toHaveLength(4);
    const reason = await query("为什么不能生产");
    expect(reason.structured_data.data.inventory_sufficient_for_requested).toBe(false);
    expect(reason.provenance).toBeTruthy();
    const history = await client.get(`/api/v1/agent/sessions/${session_id}`);
    expect(history.status()).toBe(200);
    expect((await history.json()).turns).toHaveLength(4);
  } finally { await client.dispose(); }
});

test("真实production Vue→Caddy→trial FastAPI：50/100、采购与刷新", async ({
  page,
}) => {
  await page.goto("/#/workspace");
  await expect(page.getByRole("note")).toContainText(
    "所有数据均为合成演示数据",
  );
  await expect(page.locator("#data-space option[value='']")).toHaveCount(0);
  async function ask(message: string) {
    const completed = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/agent/query") &&
        r.request().method() === "POST",
    );
    await page.getByLabel("输入分析问题").fill(message);
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    const response = await completed;
    expect(response.status()).toBe(200);
    return response.json();
  }
  const fifty = await ask("生产50台DEMO-PMC-01");
  expect(fifty.structured_data.data.inventory_sufficient_for_requested).toBe(
    true,
  );
  const hundred = await ask("生产100台DEMO-PMC-01");
  expect(hundred.structured_data.data.inventory_sufficient_for_requested).toBe(
    false,
  );
  expect(
    hundred.structured_data.data.materials
      .filter((m: any) => m.is_ready === false)
      .map((m: any) => m.shortage_qty)
      .sort(),
  ).toEqual(["100", "200", "25", "50"]);
  const purchase = await ask("帮我生成采购建议");
  expect(purchase.structured_data.data.recommendations).toHaveLength(4);
  expect(purchase.structured_data.data.total_purchase_cost).toBe("1560.00");
  await page.reload();
  await expect(page.locator(".assistant-message")).toHaveCount(3);
  await expect(page.locator("#analysis-result")).toContainText("1560");
  await expect(page.getByRole("note")).toBeVisible();
});

test("真实代理拒绝另一用户访问已存在会话", async ({ playwright }) => {
  const a = await playwright.request.newContext({
    baseURL: "http://127.0.0.1:8080",
    httpCredentials: {
      username: "trial-a",
      password: process.env.PMC_E2E_PASSWORD!,
    },
  });
  const b = await playwright.request.newContext({
    baseURL: "http://127.0.0.1:8080",
    httpCredentials: {
      username: "trial-b",
      password: process.env.PMC_E2E_PASSWORD!,
    },
  });
  try {
    const created = await a.post("/api/v1/agent/sessions", { data: {} });
    expect(created.status()).toBe(200);
    const { session_id } = await created.json();
    expect((await b.get(`/api/v1/agent/sessions/${session_id}`, {
      headers: {"X-PMC-User": "trial-a", "X-PMC-Proxy-Key": process.env.PMC_TRIAL_PROXY_SECRET!},
    })).status()).toBe(404);
    expect((await b.get(`/api/v1/agent/sessions/${session_id}`)).status()).toBe(
      404,
    );
    expect(
      (
        await b.post("/api/v1/agent/query", {
          data: { message: "生产50台DEMO-PMC-01", session_id },
        })
      ).status(),
    ).toBe(404);
    expect((await a.get(`/api/v1/agent/sessions/${session_id}`)).status()).toBe(
      200,
    );
  } finally {
    await a.dispose();
    await b.dispose();
  }
});
