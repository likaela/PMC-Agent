import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import {
  inventory,
  production,
  purchase,
  envelope,
  scenarioId,
} from "./agentFixtures";
import { httpFixtureServer } from "./httpFixtureServer";
import type { BackendResponse } from "../src/data/model";

const screenshots = "test-results/screenshots";
mkdirSync(screenshots, { recursive: true });
// All business fixtures below are served by the test HTTP harness, never the application.
function response(message: string): BackendResponse | "network" | "invalid" {
  if (message === "模拟请求失败与重试") return "network";
  if (message === "模拟映射失败") return "invalid";
  if (message === "版本冲突")
    return envelope("bom", null, {
      status: "invalid_query",
      answer: "BOM适用版本存在冲突，请确认版本。",
    });
  if (message === "单位缺失")
    return envelope("production_capacity", null, {
      status: "data_unavailable",
      answer: "缺少单位换算依据，暂无法计算。",
    });
  if (message === "无库存事实")
    return inventory({
      status: "data_unavailable",
      structured_data: null,
      answer: "暂无该物料的已发布库存数据。",
    });
  if (message === "零库存")
    return envelope(
      "inventory",
      {
        canonical_item: {
          material_code: "MAT-ZERO",
          name: "零库存物料",
          unit: "pcs",
        },
        on_hand_qty: "0",
        available_qty: "0",
        reserved_qty: null,
      },
      { answer: "已发布在库数量和可用数量均为0。" },
    );
  if (message === "查询主板库存")
    return inventory({ answer: "主板在库数量100.000，权威可用库存未知。" });
  if (message === "采购建议") return purchase();
  if (message === "生产50台DEMO-PMC-01") return production(50);
  if (message === "生产100台DEMO-PMC-01") return production(100);
  if (message === "生产1000台ABC-1000")
    return envelope(
      "production_capacity",
      {
        product: "ABC-1000",
        product_unit: "pcs",
        requested_quantity: 1000,
        inventory_sufficient_for_requested: false,
        materials: [
          {
            material_code: "BOARD",
            name: "主板",
            unit: "pcs",
            required_qty: "1000",
            available_qty: "800",
            shortage_qty: "200",
            is_ready: false,
          },
          {
            material_code: "MOTOR",
            name: "电机",
            unit: "pcs",
            required_qty: "2000",
            available_qty: null,
            shortage_qty: null,
            is_ready: null,
          },
          {
            material_code: "SCREW",
            name: "螺丝",
            unit: "pcs",
            required_qty: "8000",
            available_qty: null,
            shortage_qty: null,
            is_ready: null,
          },
        ],
      },
      { answer: "主板存在缺口，其他物料可用库存未知。" },
    );
  return envelope("production_capacity", null, {
    status: "data_unavailable",
    answer: "当前事实库没有相应的已发布数据。",
  });
}
async function send(page: Page, text: string) {
  await page.getByLabel("输入分析问题").fill(text);
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}
async function start(page: Page, delay = 0) {
  const requests = await httpFixtureServer(page, response, delay);
  await page.goto("/#/workspace");
  return requests;
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test("首页进入空白企业工作台，HTTP资料缺口和缺失库存保持真实边界", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const requests = await httpFixtureServer(page, response);
  await page.goto("/");
  await page
    .getByRole("button", { name: "输入产品编码和生产数量", exact: true })
    .click();
  await expect(page.getByLabel("输入分析问题")).toHaveValue("");
  await send(page, "生产1000台ABC-1000");
  const board = page.getByRole("row").filter({ hasText: "主板" });
  for (const value of ["1,000", "800", "200"])
    await expect(board).toContainText(value);
  for (const material of ["电机", "螺丝"]) {
    const row = page.getByRole("row").filter({ hasText: material });
    await expect(
      row.getByRole("cell", { name: "未知", exact: true }),
    ).toHaveCount(1);
    await expect(
      row.getByRole("cell", { name: "未提供", exact: true }),
    ).toHaveCount(1);
  }
  await page.getByRole("button", { name: "查看主板来源", exact: true }).click();
  await expect(
    page.getByText("inventory_facts.json", { exact: true }).first(),
  ).toBeVisible();
  expect(requests.filter((r) => r.url.endsWith("/query"))).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("库存查询和历史回答完整同步，不重发查询", async ({ page }) => {
  const requests = await start(page);
  await send(page, "生产1000台ABC-1000");
  await send(page, "查询主板库存");
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.locator(".assistant-message").first().click();
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.locator(".assistant-message").last().click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".summary-grid")).not.toContainText("ABC-1000");
  expect(requests.filter((r) => r.url.endsWith("/query"))).toHaveLength(2);
});

test("零库存与无已发布事实严格区分", async ({ page }) => {
  await start(page);
  await send(page, "零库存");
  await expect(page.locator("tbody tr td").nth(2)).toHaveText("0 pcs");
  await send(page, "无库存事实");
  await expect(
    page.getByRole("heading", { name: "已发布事实不足" }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".result-body")).not.toContainText("0 pcs");
});

test("后端合成Demo齐套与采购建议可用且不混入企业分析", async ({ page }) => {
  const requests = await start(page);
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await send(page, "生产50台DEMO-PMC-01");
  await expect(
    page.getByRole("heading", { name: "本次需求库存齐套" }),
  ).toBeVisible();
  await send(page, "采购建议");
  await expect(
    page.getByRole("heading", { name: "已发布事实采购建议" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table").filter({ hasText: "成本 / 币种" }),
  ).toContainText("600.00");
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await send(page, "生产1000台ABC-1000");
  await expect(page.getByLabel("数据空间")).toHaveValue("");
  await expect(page.getByLabel("采购建议表")).toHaveCount(0);
  expect(
    requests.filter((r) => r.url.endsWith("/query")).at(-1)!.body,
  ).not.toHaveProperty("scenario_id");
});

test("条件冲突、无法计算、映射失败不输出错误数字", async ({ page }) => {
  await start(page);
  for (const [text, heading] of [
    ["版本冲突", "请确认查询条件"],
    ["单位缺失", "已发布事实不足"],
    ["模拟映射失败", "当前结果暂无法完整展示"],
  ]) {
    await send(page, text!);
    await expect(
      page.getByRole("heading", { name: heading!, exact: true }),
    ).toBeVisible();
    await expect(page.locator("tbody")).toHaveCount(0);
  }
  await expect(page.locator(".diagnostic")).toHaveCount(0);
});

test("网络错误可恢复后重试原问题，并可重新查询成功", async ({ page }) => {
  const requests = await start(page);
  await send(page, "模拟请求失败与重试");
  await expect(
    page.getByRole("heading", { name: "请求失败，请重试" }),
  ).toBeVisible();
  await expect(page.getByLabel("输入分析问题")).toHaveValue(
    "模拟请求失败与重试",
  );
  await page.getByRole("button", { name: "重试原问题", exact: true }).click();
  await expect
    .poll(() => requests.filter((r) => r.url.endsWith("/query")).length)
    .toBe(2);
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator(".user-message")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "请求失败，请重试" }),
  ).toBeVisible();
  await send(page, "查询主板库存");
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
});

test("不匹配型号或数量必须访问后端，不套用固定结果", async ({ page }) => {
  const requests = await start(page);
  for (const question of ["生产200台ABC-1000", "生产1000台XYZ-2000"]) {
    await send(page, question);
    await expect(
      page.getByRole("heading", { name: "已发布事实不足" }),
    ).toBeVisible();
    await expect(page.locator("tbody")).toHaveCount(0);
  }
  expect(requests.filter((r) => r.url.endsWith("/query"))).toHaveLength(2);
});

test("新请求清除旧结果，取消后旧请求不覆盖新结果", async ({ page }) => {
  await start(page, 750);
  await send(page, "生产1000台ABC-1000");
  await page.getByLabel("输入分析问题").fill("零库存");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.getByLabel("输入分析问题")).toBeDisabled();
  await expect(page.locator(".result-body")).toHaveCount(0);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本次分析已取消" }),
  ).toBeVisible();
  await send(page, "查询主板库存");
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
  await expect(page.locator(".user-message")).toHaveCount(3);
});

test("数据空间切换隔离Demo，企业HTTP失败不回退本地响应", async ({ page }) => {
  const requests = await start(page);
  await page.getByLabel("数据空间").selectOption(scenarioId);
  await send(page, "生产50台DEMO-PMC-01");
  await page.getByLabel("数据空间").selectOption("");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await send(page, "模拟请求失败与重试");
  await expect(page.locator(".error-state")).toBeVisible();
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".mode-banner")).toContainText("完整追溯范围");
  expect(
    requests.filter((r) => r.url.endsWith("/query")).at(-1)!.body,
  ).not.toHaveProperty("scenario_id");
});

test("物料筛选、搜索、排序与新建分析", async ({ page }) => {
  await start(page);
  await send(page, "生产1000台ABC-1000");
  await page.getByLabel("筛选物料状态").selectOption("shortage");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText("主板");
  await page.getByLabel("搜索物料").fill("不存在");
  await expect(
    page.getByText("没有匹配的物料，请调整搜索或筛选。"),
  ).toBeVisible();
  await page.getByLabel("搜索物料").fill("");
  await page.getByLabel("筛选物料状态").selectOption("all");
  await page.getByRole("button", { name: "物料名称", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.getByRole("button", { name: "新建分析", exact: true }).click();
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.locator("tbody")).toHaveCount(0);
});

test("键盘换行、组合输入保护、Enter发送和帮助弹窗", async ({ page }) => {
  await start(page);
  const input = page.getByLabel("输入分析问题");
  await input.fill("查询主板库存");
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("查询主板库存\n");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await input.dispatchEvent("compositionstart");
  await input.press("Enter");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await input.dispatchEvent("compositionend");
  await input.fill("查询主板库存");
  await input.press("Enter");
  await expect(
    page.getByRole("heading", { name: "物料库存事实" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "使用说明", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

for (const width of [1440, 1280, 1024, 390, 320]) {
  test(
    width + "px 首页与工作台无整页横向溢出，表格局部滚动",
    async ({ page }) => {
      await httpFixtureServer(page, response);
      await page.setViewportSize({ width, height: width < 760 ? 844 : 1080 });
      await page.goto("/");
      await noOverflow(page);
      if (width === 1440 || width === 390)
        await page.screenshot({
          path: join(screenshots, "home-" + width + ".png"),
          fullPage: true,
        });
      if (width < 760) {
        await page
          .getByRole("button", { name: "打开导航", exact: true })
          .click();
        await page
          .getByRole("link", { name: "分析工作台", exact: true })
          .click();
      } else
        await page.getByRole("link", { name: "开始分析", exact: true }).click();
      await send(page, "生产1000台ABC-1000");
      await noOverflow(page);
      if (width < 760)
        expect(
          await page
            .locator(".table-scroll")
            .evaluate((el) => el.scrollWidth > el.clientWidth),
        ).toBe(true);
      await page.screenshot({
        path: join(screenshots, "workspace-" + width + ".png"),
        fullPage: true,
      });
      await page
        .getByRole("button", { name: "查看主板来源", exact: true })
        .click();
      await noOverflow(page);
      await expect(
        page.getByText("来源发布时间", { exact: true }),
      ).toBeVisible();
      if (width === 1440 || width === 390)
        await page.screenshot({
          path: join(screenshots, "sources-" + width + ".png"),
          fullPage: true,
        });
    },
  );
}
