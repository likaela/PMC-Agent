import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { inventory, envelope, scenarioId } from "./agentFixtures";
import { httpFixtureServer } from "./httpFixtureServer";
import { preferenceKey, sessionKey } from "../src/services/sessionStorage";
import { adaptBackendResponse } from "../src/services/responseAdapter";

test("企业首屏无预选产品、无场景、无本地回答（即使旧环境配置为 mock）", async ({
  page,
}) => {
  const requests = await httpFixtureServer(page, () => inventory());
  await page.goto("/#/workspace");
  await expect(page.getByLabel("数据模式")).toHaveValue("live");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("DEMO-PMC-01");
  await expect(page.locator("tbody")).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("旧 session/localStorage 的 mock + Demo 不能截获企业 BOM 请求", async ({
  page,
}) => {
  const preference = preferenceKey("http://127.0.0.1:8000");
  const demoKey = sessionKey("http://127.0.0.1:8000", scenarioId);
  await page.addInitScript(
    ({ preference, demoKey, scenarioId }) => {
      for (const storage of [localStorage, sessionStorage]) {
        storage.setItem(
          preference,
          JSON.stringify({
            mode: "mock",
            scenario_id: scenarioId,
            demo_selected: true,
          }),
        );
        storage.setItem(
          demoKey,
          JSON.stringify({ session_id: "old-demo", scenario_id: scenarioId }),
        );
      }
    },
    { preference, demoKey, scenarioId },
  );
  const response = envelope(
    "bom",
    { product: "KQ-Z112", revision: "V01", lines: [] },
    { answer: "企业 HTTP 返回的 BOM" },
  );
  const requests = await httpFixtureServer(page, () => response);
  await page.goto("/#/workspace");
  await page.getByLabel("输入分析问题").fill("查询KQ-Z112的BOM");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator(".assistant-message")).toContainText(
    response.answer,
  );
  expect(requests.map(({ url, method }) => ({ url, method }))).toEqual([
    { url: "http://127.0.0.1:8000/api/v1/agent/sessions", method: "POST" },
    { url: "http://127.0.0.1:8000/api/v1/agent/query", method: "POST" },
  ]);
  expect(requests[0]!.body).toEqual({});
  expect(requests[1]!.body).toEqual({
    message: "查询KQ-Z112的BOM",
    session_id: "http-session-1",
    persist_session: true,
  });
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), preference),
  ).toBeNull();
  // Explicit backend Demo recovery pointers remain available, but were never queried.
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), demoKey),
  ).toContain("old-demo");
});

for (const failure of ["network", "500", "invalid"] as const) {
  test(`API ${failure} 只展示错误，不显示本地成功或假库存`, async ({
    page,
  }) => {
    const requests = await httpFixtureServer(page, () => failure);
    await page.goto("/#/workspace");
    await page.getByLabel("输入分析问题").fill("查询主板库存");
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    await expect(page.locator(".error-state")).toBeVisible();
    await expect(page.locator("tbody")).toHaveCount(0);
    await expect(page.locator(".result-body")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText("PRIVATE_EXCEPTION");
    await expect(page.getByLabel("数据模式")).toHaveValue("live");
    expect(requests.filter((r) => r.url.endsWith("/query"))).toHaveLength(1);
  });
}

test("后端 data_unavailable 保留实际回答，不能补成功或库存数字", async ({
  page,
}) => {
  const answer = "当前没有KQ-Z112的已发布库存数据。";
  await httpFixtureServer(page, () =>
    envelope("inventory", null, {
      status: "data_unavailable",
      answer,
      provenance: null,
    }),
  );
  await page.goto("/#/workspace");
  await page.getByLabel("输入分析问题").fill("查询KQ-Z112库存");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator(".assistant-message")).toContainText(answer);
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".result-body")).not.toContainText("800");
});

test("新建企业分析清除后端 Demo 场景，之后请求不携带 scenario_id", async ({
  page,
}) => {
  const requests = await httpFixtureServer(page, () => inventory());
  await page.goto("/#/workspace");
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await page.getByLabel("输入分析问题").fill("查询MAT-001库存");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator(".result-body")).toBeVisible();
  for (const request of requests)
    expect(request.body).not.toHaveProperty("scenario_id");
});

test("responseAdapter 不从回答文字制造库存事实，Decimal 和 null 原样保留", () => {
  const response = inventory({
    answer: "故意声称还有999999件，不能用于卡片。",
  });
  const view = adaptBackendResponse(response);
  expect(view.materials[0]!.onHand).toBe("100.000");
  expect(view.materials[0]!.available).toBeNull();
  expect(view.materials[0]!.reserved).toBeNull();
  expect(view.materials[0]!.shortage).toBeNull();
  expect(JSON.stringify(view.metrics)).not.toContain("999999");
  expect(adaptBackendResponse(envelope("inventory", null)).materials).toEqual(
    [],
  );
});

test("生产源码入口不再依赖本地 mock service 或 fixtures", () => {
  for (const path of [
    "src/composables/useAgent.ts",
    "src/views/WorkspaceView.vue",
    "src/views/HomeView.vue",
  ]) {
    const source = readFileSync(path, "utf8");
    expect(source).not.toMatch(/import.*(?:mockService|fixtures)/);
    expect(source).not.toContain("mockService.query");
    expect(source).not.toContain("VITE_DATA_MODE");
  }
});
