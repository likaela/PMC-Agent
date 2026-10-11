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
import { preferenceKey, sessionKey } from "../src/services/sessionStorage";

// Legacy transport cases have no product catalog. Keep unmocked UI-only cases
// independent of a developer's live enterprise backend on port 8000.
test.beforeEach(async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/v1/agent/catalog", route =>
    route.fulfill({ status: 404, json: {} }));
});

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
  const reads: { session_id: string; scenario_id: string | null }[] = [];
  let activeScenario: ScenarioId | undefined;
  await page.route("http://127.0.0.1:8000/api/v1/agent/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/catalog")) { await route.fulfill({status: 404, json: {}}); return; }
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
      reads.push({
        session_id: path.split("/").at(-1)!,
        scenario_id: new URL(request.url()).searchParams.get("scenario_id"),
      });
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
    reads,
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
  await expect(page.locator("tbody")).toContainText("未知");
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
test("刷新先进入企业空间，显式选择后恢复 Demo 历史而不重新分析", async ({ page }) => {
  const backend = await server(page, () => production(50));
  await online(page, true);
  await send(page, "生产50台DEMO-PMC-01");
  await page.reload();
  await expect(page.getByLabel("数据模式")).toHaveValue("live");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  expect(backend.reads).toEqual([]);
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await expect(page.getByLabel("数据空间")).toHaveValue(scenarioId);
  await expect(
    page.getByRole("heading", { name: "本次需求库存齐套" }),
  ).toBeVisible();
  await expect(page.locator(".message-pair")).toHaveCount(1);
  expect(backend.requests).toHaveLength(1);
  expect(backend.reads).toEqual([
    { session_id: "session-1", scenario_id: scenarioId },
  ]);
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

test("首页隔离 Demo 显式选择后只提交场景问题，不展示旧 mock 缺口数字", async ({
  page,
}) => {
  const backend = await server(page, () => production(50));
  await page.goto("/");
  await page.getByLabel("数据模式").selectOption("live");
  await expect(page.locator(".hero")).not.toContainText("200 件");
  await expect(page.locator("body")).not.toContainText("DEMO-PMC-01");
  await page
    .getByRole("button", { name: "体验演示产品", exact: true })
    .click();
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

test("企业首页不预设 Demo 产品，开始分析进入空白企业会话", async ({ page }) => {
  const key = preferenceKey("http://127.0.0.1:8000");
  await page.addInitScript((key) => {
    sessionStorage.setItem(key, JSON.stringify({ mode: "live" }));
  }, key);
  const backend = await server(page, () => inventory());
  await page.goto("/");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.locator("body")).not.toContainText("DEMO-PMC-01");
  await page.getByRole("link", { name: "开始分析", exact: true }).click();
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  await expect(page.getByLabel("输入分析问题")).toHaveAttribute(
    "placeholder",
    /产品编码/,
  );
  await expect(page.locator(".welcome-message")).toContainText(
    "请先输入企业产品编码",
  );
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.locator("tbody")).toHaveCount(0);
  expect(backend.creates).toBe(0); // Existing contract: create server session on first send.
  await send(page, "查询MAT-001库存");
  expect(backend.creates).toBe(1);
  expect(backend.requests[0].scenario_id).toBeUndefined();
});

test("未发送消息也可从 Demo 新建空白企业分析", async ({ page }) => {
  await online(page, true);
  await page.getByLabel("输入分析问题").fill("生产100台DEMO-PMC-01");
  await expect(
    page.getByRole("button", { name: "新建分析", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await expect(page.getByLabel("数据模式")).toHaveValue("live");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  await expect(page.locator(".quick-questions")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("DEMO-PMC-01");
  expect(await state(page)).toEqual({
    scenario_id: null,
    session_id: null,
    result: null,
  });
});

test("Demo 分析后新建企业会话不继承 Demo 或恢复旧企业指针", async ({
  page,
}) => {
  const backend = await server(page, (message) =>
    message.startsWith("查询") ? inventory() : production(50),
  );
  await online(page, true);
  await send(page, "生产50台DEMO-PMC-01");
  const staleKey = sessionKey("http://127.0.0.1:8000");
  await page.evaluate((key) => {
    sessionStorage.setItem(
      key,
      JSON.stringify({ session_id: "stale-enterprise" }),
    );
  }, staleKey);
  const restorations: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      request.url().includes("/agent/sessions/")
    )
      restorations.push(request.url());
  });
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("DEMO-PMC-01");
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), staleKey),
  ).toBeNull();
  await send(page, "查询MAT-001库存");
  expect(backend.creates).toBe(2);
  expect(backend.requests[0].scenario_id).toBe(scenarioId);
  expect(backend.requests[1]).toMatchObject({
    session_id: "session-2",
    persist_session: true,
  });
  expect(backend.requests[1].scenario_id).toBeUndefined();
  expect(restorations).toEqual([]);
});

async function state(page: Page) {
  return page.evaluate(async () => {
    const modulePath = "/src/composables/useAgent.ts";
    const { useAgent } = await import(modulePath);
    const agent = useAgent();
    return {
      scenario_id: agent.scenario.value,
      session_id: agent.sessionId.value,
      result: agent.result.value,
    };
  });
}

test("旧 Demo 偏好与 localStorage 不能将首次企业入口切换为 Demo", async ({
  page,
}) => {
  const keys = {
    preference: preferenceKey("http://127.0.0.1:8000"),
    demo: sessionKey("http://127.0.0.1:8000", scenarioId),
  };
  await page.addInitScript(({ preference, demo }) => {
    sessionStorage.setItem(
      preference,
      JSON.stringify({ mode: "live", scenario_id: "demo_scenario_50_vs_100" }),
    );
    sessionStorage.setItem(
      demo,
      JSON.stringify({
        session_id: "old-demo",
        scenario_id: "demo_scenario_50_vs_100",
      }),
    );
    localStorage.setItem(
      preference,
      JSON.stringify({
        mode: "live",
        scenario_id: "demo_scenario_50_vs_100",
        demo_selected: true,
      }),
    );
    localStorage.setItem(
      demo,
      JSON.stringify({
        session_id: "local-demo",
        scenario_id: "demo_scenario_50_vs_100",
      }),
    );
  }, keys);
  const backend = await server(page, () => inventory());
  await page.goto("/#/workspace");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  expect(await state(page)).toEqual({
    scenario_id: null,
    session_id: null,
    result: null,
  });
  await page.reload(); // Legacy preference without an explicit selection marker stays enterprise.
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  expect(await state(page)).toEqual({
    scenario_id: null,
    session_id: null,
    result: null,
  });
  expect(backend.creates).toBe(0);
  expect(backend.reads).toEqual([]);
});

test("URL 场景参数不能自动注入 Demo，必须主动选择", async ({ page }) => {
  await page.goto("/#/workspace?scenario=demo-50");
  await page.getByLabel("数据模式").selectOption("live");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  expect(await state(page)).toEqual({
    scenario_id: null,
    session_id: null,
    result: null,
  });
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await expect(page.locator(".quick-questions")).toHaveCount(0);
  await page.getByRole("button", {name:"展开推荐问题"}).click();
  await expect(page.locator(".quick-questions")).toContainText("50 台齐套分析");
});

test("企业刷新恢复原会话且不携带 Demo 标识或重新分析", async ({ page }) => {
  const backend = await server(page, () => inventory());
  await online(page);
  await send(page, "查询MAT-001库存");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.locator(".message-pair")).toHaveCount(1);
  const agent = await state(page);
  expect(agent.scenario_id).toBeNull();
  expect(agent.session_id).toBe("session-1");
  expect(agent.result).not.toBeNull();
  expect(backend.reads).toEqual([
    { session_id: "session-1", scenario_id: null },
  ]);
  expect(backend.requests).toHaveLength(1);
});

for (const wrongScope of ["header", "turn"]) {
  test(`企业历史恢复拒绝跨 Demo ${wrongScope} 数据`, async ({ page }) => {
    const backend = await server(page, () => inventory());
    await online(page);
    await send(page, "查询MAT-001库存");
    await page.route(
      "http://127.0.0.1:8000/api/v1/agent/sessions/*?*",
      (route) =>
        route.fulfill({
          json: {
            ...session,
            session_id: "session-1",
            scenario_id: wrongScope === "header" ? scenarioId : null,
            turns: [
              {
                ...backend.turns[0],
                response: {
                  ...backend.turns[0].response,
                  scenario_id: scenarioId,
                },
              },
            ],
          },
        }),
    );
    await page.reload();
    await expect(
      page.getByText("当前会话已失效，请新建分析。", { exact: true }),
    ).toBeVisible();
    expect(await state(page)).toEqual({
      scenario_id: null,
      session_id: null,
      result: null,
    });
    await expect(page.locator(".message-pair")).toHaveCount(0);
    expect(backend.requests).toHaveLength(1);
  });
}

test("企业创建会话返回错误 Demo 空间时不发送业务查询", async ({ page }) => {
  const backend = await server(page, () => inventory());
  await online(page);
  await page.route("http://127.0.0.1:8000/api/v1/agent/sessions", (route) =>
    route.fulfill({ json: { ...session, scenario_id: scenarioId } }),
  );
  await send(page, "查询MAT-001库存");
  await expect(page.locator(".message-list")).toContainText("未发送分析请求");
  expect(backend.requests).toEqual([]);
  expect((await state(page)).session_id).toBeNull();
});
