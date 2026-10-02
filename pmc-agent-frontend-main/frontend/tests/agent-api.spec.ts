import { test, expect, type Page } from "@playwright/test";
import {
  inventory,
  production,
  purchase,
  session,
  scenarioId,
  envelope,
} from "./agentFixtures";
import type {
  BackendResponse,
  BackendTurn,
  ScenarioId,
} from "../src/data/model";

async function online(page: Page, demo = false) {
  await page.goto("/#/workspace");
  await page.getByLabel("数据模式").selectOption("live");
  if (demo) await page.getByLabel("数据空间").selectOption(scenarioId);
}
async function send(page: Page, message: string) {
  await page.getByLabel("输入分析问题").fill(message);
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}
async function server(
  page: Page,
  makeResponse: (message: string) => BackendResponse,
) {
  const requests: Record<string, unknown>[] = [];
  const turns: BackendTurn[] = [];
  let creates = 0;
  let activeScenario: ScenarioId | undefined;
  await page.route("http://127.0.0.1:8000/api/v1/agent/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/sessions") && request.method() === "POST") {
      creates++;
      activeScenario = request.postDataJSON()?.scenario_id;
      await route.fulfill({
        json: {
          ...session,
          session_id: "session-" + creates,
          scenario_id: activeScenario,
        },
      });
      return;
    }
    if (request.method() === "GET") {
      const after = Number(
        new URL(request.url()).searchParams.get("after") ?? 0,
      );
      await route.fulfill({
        json: {
          ...session,
          session_id: "session-" + creates,
          scenario_id: activeScenario,
          turns: turns.filter((t) => t.sequence_no > after),
        },
      });
      return;
    }
    const body = request.postDataJSON();
    requests.push(body);
    const response = {
      ...makeResponse(body.message),
      session_id: body.session_id,
      scenario_id: activeScenario,
      turn_id: "turn-" + (turns.length + 1),
    };
    turns.push({
      turn_id: response.turn_id,
      sequence_no: turns.length + 1,
      user_query: body.message,
      response,
      created_at: "2026-10-02T00:00:00Z",
    });
    await route.fulfill({ json: response });
  });
  return {
    requests,
    turns,
    get creates() {
      return creates;
    },
  };
}

test("在线库存查询使用 Agent API，null 不变零且可展示来源", async ({
  page,
}) => {
  const backend = await server(page, () => inventory());
  await online(page);
  await send(page, "查询MAT-001库存");
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toContainText("100.000");
  await expect(page.locator("tbody")).toContainText("未提供");
  expect(backend.requests[0]).toMatchObject({
    message: "查询MAT-001库存",
    session_id: "session-1",
    persist_session: true,
  });
  expect(backend.requests[0]).not.toHaveProperty("workflow_id");
  await page.getByRole("button", { name: "查看主板来源", exact: true }).click();
  await expect(
    page.getByText("inventory_facts.json", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("库存快照时点", { exact: true })).toBeVisible();
  await expect(page.getByText("7", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => Object.values(sessionStorage).join("")),
  ).toContain("session-1");
  expect(
    await page.evaluate(() => Object.values(sessionStorage).join("")),
  ).not.toContain("100.000");
});
test("50/100 台 Demo 使用同一持久会话，分别齐套和缺料", async ({ page }) => {
  const backend = await server(page, (message) =>
    message.includes("100") ? production(100) : production(50),
  );
  await online(page, true);
  await send(page, "生产50台DEMO-PMC-01");
  await expect(
    page.getByRole("heading", { name: "本次需求库存齐套" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await send(page, "生产100台DEMO-PMC-01");
  await expect(
    page.getByRole("heading", { name: "本次需求存在物料缺口" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("25");
  expect(backend.creates).toBe(1);
  expect(
    backend.requests.every(
      (r) => r.scenario_id === scenarioId && r.session_id === "session-1",
    ),
  ).toBe(true);
});
test("无库存事实显示不可用，不套用 offline 样例", async ({ page }) => {
  await server(page, () =>
    envelope("inventory", null, {
      status: "data_unavailable",
      answer: "已找到物料，但没有已发布库存数据。",
    }),
  );
  await online(page);
  await send(page, "查询MAT-001库存");
  await expect(
    page.getByRole("heading", { name: "已发布事实不足" }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".result-body")).not.toContainText("800");
});
test("采购建议表展示服务端数量、成本与风险", async ({ page }) => {
  await server(page, () => purchase());
  await online(page, true);
  await send(page, "采购建议");
  await expect(
    page.getByRole("heading", { name: "已发布事实采购建议" }),
  ).toBeVisible();
  const table = page.getByLabel("采购建议表");
  await expect(table).toContainText("30");
  await expect(table).toContainText("600.00");
  await expect(table).toContainText("高风险");
});
test("刷新恢复同一 Demo 会话和历史回答，不重新发送分析", async ({ page }) => {
  const backend = await server(page, () => production(50));
  await online(page, true);
  await send(page, "生产50台DEMO-PMC-01");
  await page.reload();
  await expect(page.getByLabel("数据模式")).toHaveValue("live");
  await expect(page.getByLabel("数据空间")).toHaveValue(scenarioId);
  await expect(
    page.getByRole("heading", { name: "本次需求库存齐套" }),
  ).toBeVisible();
  await expect(page.locator(".message-pair")).toHaveCount(1);
  expect(backend.requests).toHaveLength(1);
});
test("新建分析清理会话指针，下次请求创建新 session", async ({ page }) => {
  const backend = await server(page, () => inventory());
  await online(page);
  await send(page, "查询MAT-001库存");
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await send(page, "查询MAT-001库存");
  expect(backend.requests.map((r) => r.session_id)).toEqual([
    "session-1",
    "session-2",
  ]);
  await expect(page.locator(".message-pair")).toHaveCount(1);
});
test("会话失效清理指针，内部异常不显示给用户", async ({ page }) => {
  await server(page, () => inventory());
  await online(page);
  await send(page, "查询MAT-001库存");
  await page.route("http://127.0.0.1:8000/api/v1/agent/sessions/*?*", (route) =>
    route.fulfill({
      status: 404,
      json: { user_message: "Traceback internal database path secret" },
    }),
  );
  await page.reload();
  await expect(
    page.getByText("当前会话已失效，请新建分析。", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Traceback");
  expect(
    await page.evaluate(() => Object.values(sessionStorage).join("")),
  ).not.toContain("session-1");
});
test("澄清信息正常显示，不伪造结果卡片数值", async ({ page }) => {
  await server(page, () =>
    envelope("clarification", null, {
      status: "needs_input",
      answer: "请补充 BOM 版本和生效日期。",
      structured_data: {
        query: { material_code: "KQ-Z112" },
        missing_fields: ["BOM版本", "生效日期"],
      },
    }),
  );
  await online(page);
  await send(page, "KQ-Z112能生产多少");
  await expect(
    page.getByRole("heading", { name: "需要补充查询信息" }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".result-body")).toContainText("生效日期");
});
test("在线手机页面不溢出", async ({ page }) => {
  await server(page, () => production(100));
  await page.setViewportSize({ width: 390, height: 844 });
  await online(page, true);
  await send(page, "生产100台DEMO-PMC-01");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("首页在线入口只提交场景问题，不展示旧 mock 缺口数字", async ({ page }) => {
  const backend = await server(page, () => production(50));
  await page.goto("/");
  await page.getByLabel("数据模式").selectOption("live");
  await expect(page.locator(".hero")).not.toContainText("200 件");
  await page
    .getByRole("button", { name: "生产50台DEMO-PMC-01", exact: true })
    .click();
  await expect(page.getByLabel("数据空间")).toHaveValue(scenarioId);
  await expect(page.getByLabel("输入分析问题")).toHaveValue(
    "生产50台DEMO-PMC-01",
  );
  expect(backend.requests).toHaveLength(0);
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本次需求库存齐套" }),
  ).toBeVisible();
  expect(backend.requests[0].scenario_id).toBe(scenarioId);
});
