import { test, expect, type Page } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session, source } from "./agentFixtures";
import type { BackendResponse, BackendTurn } from "../src/data/model";

function bom(code = "EXAMPLE-PRODUCT-A", count = 2): BackendResponse {
  return envelope(
    "bom",
    {
      parent_item: { material_code: code, unit: "片" },
      revision: "V01",
      effective_from: "2026-03-01",
      line_count: count,
      lines: Array.from({ length: count }, (_, index) => ({
        child_item: { material_code: `EXAMPLE-M-${index}`, unit: null },
        qty_per: "2.5",
        unit: "片",
        price: null,
      })),
    },
    {
      answer: `${code} 的已发布 BOM。部分物料价格尚未确认，暂不能进行完整成本计算。`,
      warnings: ["price_missing：缺少权威价格"],
    },
  );
}
function greeting(): BackendResponse {
  return envelope("clarification", null, {
    answer: "您好，我是制造企业的PMC助手。",
    structured_data: {
      operation: "conversation",
      completed_steps: [],
      query: {},
      data: null,
    },
    provenance: null,
  });
}

test("普通BOM屏蔽价格展示但保留null及技术完整性", () => {
  const backend = bom();
  Object.assign(backend.structured_data!, {
    completeness: { unit: true, price: false },
  });
  const before = JSON.stringify(backend);
  const vm = adaptBackendResponse(backend, "查询EXAMPLE-PRODUCT-A的BOM");
  expect(vm.answer).not.toContain("价格");
  expect(vm.warnings).toEqual([]);
  expect(vm.metrics?.find((m) => m.label === "待核实事实")).toBeUndefined();
  expect(vm.completeness?.price).toBe(false);
  expect(vm.materials[0].qtyPer).toBe("2.5");
  expect(vm.materials[0].available).toBeNull();
  expect(vm.materials[0].shortage).toBeNull();
  expect(JSON.stringify(backend)).toBe(before);
});

test("明确成本询问保留价格不足提示和来源", () => {
  const backend = envelope("purchase_planning", null, {
    status: "data_unavailable",
    answer: "目前缺少可靠的价格数据，暂时无法计算完整成本。",
    warnings: ["price_missing：缺少权威价格"],
    structured_data: {
      query: { material_code: "EXAMPLE-PRODUCT-A" },
      data: null,
      completeness: { price: false, cost: false },
      presentation: { price_relevant: true },
    },
    provenance: source,
  });
  const vm = adaptBackendResponse(backend, "完整成本多少钱？");
  expect(vm.answer).toContain("缺少可靠的价格数据");
  expect(vm.warnings[0]).toContain("price_missing");
  expect(vm.metrics?.find((m) => m.label === "待核实事实")).toBeUndefined();
  expect((vm.backend?.structured_data?.completeness as Record<string,unknown>).price).toBe(false);
  expect(vm.sources.length).toBeGreaterThan(0);
});

test("问候标记由结构契约决定，不猜回答文本", () => {
  const vm = adaptBackendResponse(greeting());
  expect(vm.conversation).toBe(true);
  expect(vm.product).toBeNull();
  expect(vm.quantity).toBeNull();
  expect(adaptBackendResponse(bom()).conversation).toBe(false);
});

async function server(page: Page) {
  const turns: BackendTurn[] = [];
  await page.route("http://127.0.0.1:8000/api/v1/agent/**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ json: { ...session, turns } });
    } else if (new URL(request.url()).pathname.endsWith("/sessions")) {
      await route.fulfill({ json: session });
    } else {
      const message = request.postDataJSON().message as string;
      if (message === "模拟连接故障") {
        await route.fulfill({ status: 500, json: { code: "ANALYSIS_UNAVAILABLE", user_message: "分析服务暂时异常，请稍后重试。" } });
        return;
      }
      const result = /你好|NIHAO/.test(message)
        ? greeting()
        : message === "查询已发布的BOM"
          ? envelope("fact_query", { products: [{ product_code: "EXAMPLE-PRODUCT-A", published_bom_status: "published", revisions: [{ revision: "V01" }] }] }, { answer: "以下为已发布产品目录，目录不是生产许可。" })
        : message.includes("EXAMPLE-PRODUCT-B")
          ? bom("EXAMPLE-PRODUCT-B", 3)
          : message.includes("不存在")
            ? envelope("bom", null, {
                status: "data_unavailable",
                answer: "当前没有该产品的已发布BOM。",
              })
            : bom();
      const response = { ...result, turn_id: `test-turn-${turns.length + 1}` };
      turns.push({
        turn_id: response.turn_id,
        sequence_no: turns.length + 1,
        user_query: message,
        response,
        created_at: "2026-10-09T00:00:00+08:00",
      });
      await route.fulfill({ json: response });
    }
  });
  return turns;
}
async function send(page: Page, message: string) {
  await page.getByLabel("输入分析问题").fill(message);
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}

test("问候清空当前业务面板；选择历史和刷新仍正确绑定", async ({ page }) => {
  const turns = await server(page);
  await page.goto("/#/workspace");
  await send(page, "查询EXAMPLE-PRODUCT-A的BOM");
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-A");
  await send(page, "NIHAO");
  await expect(
    page.getByRole("heading", { name: "本轮为交流回复" }),
  ).toBeVisible();
  await expect(page.locator(".result-body")).toHaveCount(0);
  await expect(page.locator(".summary-grid")).not.toContainText(
    "EXAMPLE-PRODUCT-A",
  );
  await page.locator(".assistant-message").first().click();
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-A");
  await expect(page.locator(".result-body")).not.toContainText("价格");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "本轮为交流回复" }),
  ).toBeVisible();
  expect(turns).toHaveLength(2);
  await page.locator(".assistant-message").first().click();
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-A");
  await expect(page.locator(".result-body")).not.toContainText("价格");
});

test("产品切换和无事实结果不残留前一个产品物料表", async ({ page }) => {
  await server(page);
  await page.goto("/#/workspace");
  await send(page, "查询EXAMPLE-PRODUCT-A的BOM");
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-A");
  await send(page, "那EXAMPLE-PRODUCT-B呢？");
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-B");
  await expect(page.locator(".result-body")).not.toContainText(
    "EXAMPLE-PRODUCT-A",
  );
  await expect(page.locator(".summary-grid")).toContainText(
    "EXAMPLE-PRODUCT-B",
  );
  await send(page, "查询不存在的BOM");
  await expect(page.locator(".result-body")).toContainText("当前没有该产品");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
});

test("目录与BOM结果随选中回答同步；刷新恢复最新已保存回答", async ({ page }) => {
  await server(page);
  await page.goto("/#/workspace");
  await send(page, "查询EXAMPLE-PRODUCT-A的BOM");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(2);
  await send(page, "查询已发布的BOM");
  await expect(page.locator(".result-body")).toContainText("已发布产品目录");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
  await page.locator(".assistant-message").first().click();
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(2);
  await page.locator(".assistant-message").last().click();
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".result-body")).toContainText("已发布产品目录");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
});

test("请求失败不显示上一个产品结果；历史仍可主动选择", async ({ page }) => {
  await server(page);
  await page.goto("/#/workspace");
  await send(page, "查询EXAMPLE-PRODUCT-A的BOM");
  await send(page, "模拟连接故障");
  await expect(page.locator("#analysis-result .error-state")).toBeVisible();
  await expect(page.locator(".result-body")).toHaveCount(0);
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(0);
  await page.locator(".assistant-message").first().click();
  await expect(page.locator(".result-body")).toContainText("EXAMPLE-PRODUCT-A");
  await expect(page.locator(".materials-card tbody tr")).toHaveCount(2);
});
