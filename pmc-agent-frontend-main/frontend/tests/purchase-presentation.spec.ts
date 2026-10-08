import { test, expect, type Page } from "@playwright/test";
import type { BackendResponse } from "../src/data/model";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { purchase, session, scenarioId } from "./agentFixtures";

function responseWith(row: Record<string, unknown> = {}): BackendResponse {
  const response = purchase();
  const data = response.structured_data!.data as Record<string, unknown>;
  const recommendation = (data.recommendations as Record<string, unknown>[])[0];
  Object.assign(recommendation, row);
  recommendation.completeness = {
    quantity: true,
    parameters: true,
    cost: true,
  };
  response.structured_data!.completeness = {
    quantity: true,
    parameters: true,
    cost: true,
  };
  return response;
}

const cases = [
  {
    name: "已有库存与采购建议独立映射",
    row: {
      available_qty: "75.000",
      shortage_qty: "25.000",
      suggested_purchase_qty: "30.000",
    },
    state: "shortage",
    available: "75.000",
    shortage: "25.000",
    suggested: "30.000",
  },
  {
    name: "已有库存但无采购建议，不标为库存未知",
    row: { shortage_qty: "0.000", suggested_purchase_qty: null },
    state: "sufficient",
    available: "75",
    shortage: "0.000",
    suggested: null,
  },
  {
    name: "仅在库已知，可用库存未知时不推算也不判缺料",
    row: {
      available_qty: null,
      shortage_qty: null,
      suggested_purchase_qty: null,
    },
    state: "unknown",
    available: null,
    shortage: null,
    suggested: null,
  },
  {
    name: "已知缺料但采购建议缺失，缺料状态仍保留",
    row: { suggested_purchase_qty: null },
    state: "shortage",
    available: "75",
    shortage: "25",
    suggested: null,
  },
] as const;

for (const sample of cases) {
  test(`采购适配：${sample.name}`, () => {
    const response = responseWith(sample.row);
    const vm = adaptBackendResponse(response);
    expect(vm.materials[0]).toMatchObject({
      state: sample.state,
      onHand: "80.000",
      reserved: "5.000",
      available: sample.available,
      shortage: sample.shortage,
      purchaseQty: sample.suggested,
      completeness: { quantity: true, parameters: true, cost: true },
    });
    expect(vm.purchases![0].suggested).toBe(sample.suggested);
    expect(vm.completeness).toEqual(response.structured_data!.completeness);
    expect(vm.backend).toBe(response);
    expect(vm.sources[0].reference).toBe("inventory_facts.json");
    expect(vm.materials[0].sourceIds).toContain(vm.sources[0].id);
  });
}

test("已知零库存不等于未知；缺口未知时只展示已提供库存", () => {
  expect(
    adaptBackendResponse(
      responseWith({ available_qty: "0", shortage_qty: "100" }),
    ).materials[0],
  ).toMatchObject({ state: "shortage", available: "0", shortage: "100" });
  expect(
    adaptBackendResponse(responseWith({ shortage_qty: null })).materials[0],
  ).toMatchObject({ state: "published", available: "75", shortage: null });
});

test("显式 null 不被备用缺口或采购字段覆盖", () => {
  const vm = adaptBackendResponse(
    responseWith({
      shortage_qty: null,
      shortage: "25",
      suggested_purchase_qty: null,
      purchase_qty: "30",
    }),
  );
  expect(vm.materials[0]).toMatchObject({
    shortage: null,
    purchaseQty: null,
    state: "published",
  });
  expect(vm.purchases![0]).toMatchObject({ shortage: null, suggested: null });
  const aliases = adaptBackendResponse(
    responseWith({
      shortage_qty: undefined,
      shortage: "25.000",
      suggested_purchase_qty: undefined,
      purchase_qty: "30.000",
    }),
  );
  expect(aliases.materials[0]).toMatchObject({
    shortage: "25.000",
    purchaseQty: "30.000",
  });
});

test("状态标签不丢 Decimal 精度，零指数不误判为缺料", () => {
  expect(
    adaptBackendResponse(responseWith({ shortage_qty: "0.000e99" }))
      .materials[0].state,
  ).toBe("sufficient");
  const vm = adaptBackendResponse(
    responseWith({ shortage_qty: "0.000000000000000000000001" }),
  );
  expect(vm.materials[0]).toMatchObject({
    state: "shortage",
    shortage: "0.000000000000000000000001",
  });
});

async function onlinePurchase(page: Page, response: BackendResponse) {
  let queries = 0;
  await page.route("http://127.0.0.1:8000/api/v1/agent/**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          ...session,
          scenario_id: scenarioId,
          turns: [
            {
              turn_id: "purchase-turn",
              sequence_no: 1,
              user_query: "采购建议",
              created_at: session.created_at,
              response,
            },
          ],
        },
      });
    } else if (new URL(request.url()).pathname.endsWith("/sessions")) {
      await route.fulfill({ json: { ...session, scenario_id: scenarioId } });
    } else {
      queries++;
      await route.fulfill({ json: response });
    }
  });
  await page.goto("/#/workspace");
  await page.getByLabel("数据模式").selectOption("live");
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await page.getByLabel("输入分析问题").fill("采购建议");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "已发布事实采购建议" }),
  ).toBeVisible();
  return () => queries;
}

for (const sample of cases) {
  test(`采购物料表：${sample.name}`, async ({ page }) => {
    await onlinePurchase(page, responseWith(sample.row));
    const table = page.getByRole("region", { name: "物料明细表，可横向滚动" });
    const cells = table.locator("tbody tr").first().getByRole("cell");
    await expect(cells.nth(2)).toHaveText(
      sample.available == null ? "未知" : `${sample.available} pcs`,
    );
    await expect(cells.nth(3)).toHaveText("80.000 pcs");
    await expect(cells.nth(4)).toHaveText("5.000 pcs");
    await expect(cells.nth(5)).toHaveText(
      sample.shortage == null ? "未提供" : `${sample.shortage} pcs`,
    );
    await expect(cells.nth(6)).toHaveText(
      sample.suggested == null ? "未知" : `${sample.suggested} pcs`,
    );
    await expect(cells.nth(7)).toHaveText(
      sample.state === "shortage"
        ? "缺料"
        : sample.state === "sufficient"
          ? "满足需求"
          : "可用库存未知",
    );
    await expect(table).not.toContainText("待补充库存");
    if (sample.state !== "sufficient") {
      await page.getByLabel("筛选物料状态").selectOption(sample.state);
      await expect(table.locator("tbody tr")).toHaveCount(1);
    }
  });
}

test("恢复采购历史仍正确映射库存、缺口、采购量与来源", async ({ page }) => {
  const queryCount = await onlinePurchase(page, responseWith());
  await page.reload();
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await page.getByLabel("数据空间").selectOption("demo_scenario_50_vs_100");
  await expect(
    page.getByRole("heading", { name: "已发布事实采购建议" }),
  ).toBeVisible();
  const table = page.getByRole("region", { name: "物料明细表，可横向滚动" });
  const cells = table.locator("tbody tr").first().getByRole("cell");
  await expect(cells.nth(2)).toHaveText("75 pcs");
  await expect(cells.nth(6)).toHaveText("30 pcs");
  await expect(cells.nth(7)).toHaveText("缺料");
  expect(queryCount()).toBe(1);
  await page
    .getByRole("button", { name: "查看DEMO-BOARD-01来源", exact: true })
    .click();
  await expect(
    page.getByText("inventory_facts.json", { exact: true }).first(),
  ).toBeVisible();
});
