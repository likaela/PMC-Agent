import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const screenshots = "test-results/screenshots";
mkdirSync(screenshots, { recursive: true });
async function scenario(page: Page, id: string) {
  await page.getByLabel("演示场景", { exact: true }).selectOption(id);
  await page.getByRole("button", { name: "填入问题", exact: true }).click();
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
}
async function start(page: Page) {
  await page.goto("/#/workspace");
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}
test("首页场景进入工作台，资料缺口和缺失库存保持真实边界", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByRole("button", {
      name: "生产 1,000 台 ABC-1000，物料够吗？",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("输入分析问题")).toHaveValue(
    "生产 1,000 台 ABC-1000，物料够吗？",
  );
  await expect(
    page.getByRole("heading", { name: "让每个问题都有清晰的落点" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "主板存在缺口，完整齐套情况待确认" }),
  ).toBeVisible();
  const board = page.getByRole("row").filter({ hasText: "主板" });
  await expect(board).toContainText("1,000");
  await expect(board).toContainText("800");
  await expect(board).toContainText("200");
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "电机" })
      .getByRole("cell", { name: "未提供", exact: true }),
  ).toHaveCount(1);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "电机" })
      .getByRole("cell", { name: "未知", exact: true }),
  ).toHaveCount(1);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "螺丝" })
      .getByRole("cell", { name: "未提供", exact: true }),
  ).toHaveCount(1);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "螺丝" })
      .getByRole("cell", { name: "未知", exact: true }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "查看主板来源", exact: true }).click();
  await expect(
    page.getByText(
      "PMC-Agent_Codex前端开发提示词.txt · 第七节（转述协作说明样例）",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("本次分析来源（未提供字段级原始定位）"),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
test("库存查询和历史回答完整同步", async ({ page }) => {
  await start(page);
  await scenario(page, "production");
  await scenario(page, "inventory");
  await expect(
    page.getByRole("heading", { name: "主板示例库存为 800 件" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.locator(".assistant-message").first().click();
  await expect(
    page.getByRole("heading", { name: "主板存在缺口，完整齐套情况待确认" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(3);
  await page.locator(".assistant-message").last().click();
  await expect(
    page.getByRole("heading", { name: "主板示例库存为 800 件" }),
  ).toBeVisible();
  await expect(page.locator(".summary-grid")).not.toContainText("ABC-1000");
});
test("零库存与无已发布事实严格区分", async ({ page }) => {
  await start(page);
  await scenario(page, "zero");
  await expect(
    page.getByRole("heading", { name: "演示物料已发布库存为 0 件" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr td").nth(2)).toHaveText("0 件");
  await scenario(page, "no-facts");
  await expect(
    page.getByRole("heading", { name: "暂无该物料的已发布库存数据" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr td").nth(2)).toHaveText("暂无已发布数据");
  await expect(page.locator("tbody")).not.toContainText("0 件");
});
test("所列齐套与独立采购样例可用且不混入项目分析", async ({ page }) => {
  await start(page);
  await scenario(page, "ready");
  await expect(
    page.getByRole("heading", { name: "所列物料满足本次演示需求" }),
  ).toBeVisible();
  await expect(page.locator(".result-body")).toContainText("人工构造演示样例");
  await scenario(page, "purchase");
  await expect(
    page.getByRole("heading", { name: "独立样例：建议采购 300 件" }),
  ).toBeVisible();
  await expect(page.locator(".purchase-grid")).toContainText("300");
  await expect(page.locator(".warning-list")).toContainText("不是 ABC-1000");
  await scenario(page, "production");
  await expect(page.locator(".purchase-grid")).toHaveCount(0);
});
test("条件冲突、无法计算、映射失败不输出错误数字", async ({ page }) => {
  await start(page);
  for (const [id, heading] of [
    ["conflict", "BOM 适用版本存在冲突"],
    ["uncalculable", "缺少单位换算依据，暂无法计算"],
    ["mapping", "当前结果暂无法完整展示"],
  ]) {
    await scenario(page, id!);
    await expect(
      page.getByRole("heading", { name: heading!, exact: true }),
    ).toBeVisible();
    await expect(page.locator("tbody")).toHaveCount(0);
  }
  await expect(page.locator(".diagnostic")).toHaveCount(0);
});
test("网络错误可重试原问题，并可切换成功场景", async ({ page }) => {
  await start(page);
  await scenario(page, "network");
  await expect(
    page.getByRole("heading", { name: "请求失败，请重试" }),
  ).toBeVisible();
  await expect(page.getByLabel("输入分析问题")).toHaveValue(
    "模拟请求失败与重试",
  );
  await page.getByRole("button", { name: "重试原问题", exact: true }).click();
  await expect(page.locator("#analysis-result")).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(page.locator(".user-message")).toHaveCount(2);
  await expect(
    page.getByRole("heading", { name: "请求失败，请重试" }),
  ).toBeVisible();
  await scenario(page, "inventory");
  await expect(
    page.getByRole("heading", { name: "主板示例库存为 800 件" }),
  ).toBeVisible();
});
test("不匹配型号或数量不得套用固定结果", async ({ page }) => {
  await start(page);
  for (const question of [
    "生产 200 台 ABC-1000，物料够吗？",
    "生产 1,000 台 XYZ-2000，物料够吗？",
  ]) {
    await page.getByLabel("输入分析问题").fill(question);
    await page.getByRole("button", { name: "发送问题", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "请选择已提供的演示场景" }),
    ).toBeVisible();
    await expect(page.locator("tbody")).toHaveCount(0);
  }
});
test("新请求清除旧结果，取消后旧请求不覆盖新结果", async ({ page }) => {
  await start(page);
  await scenario(page, "production");
  await page.getByLabel("演示场景", { exact: true }).selectOption("ready");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "主板存在缺口，完整齐套情况待确认" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("输入分析问题")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "发送问题", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本次分析已取消" }),
  ).toBeVisible();
  await scenario(page, "inventory");
  await expect(
    page.getByRole("heading", { name: "主板示例库存为 800 件" }),
  ).toBeVisible();
  await expect(page.locator(".user-message")).toHaveCount(3);
});
test("模式切换中止请求并隔离演示，live 失败不回退 mock", async ({ page }) => {
  const apiRequests: string[] = [];
  await page.route("http://127.0.0.1:8000/api/**", (route) => route.abort());
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  await start(page);
  await page
    .getByRole("button", {
      name: "生产 1,000 台 ABC-1000，物料够吗？",
      exact: true,
    })
    .click();
  await page.getByLabel("数据模式").selectOption("live");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(page.getByLabel("演示场景", { exact: true })).toHaveCount(0);
  await page.getByLabel("输入分析问题").fill("查询主板库存");
  await page.getByRole("button", { name: "发送问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "请求失败，请重试", exact: true }),
  ).toBeVisible();
  await expect(page.locator("tbody")).toHaveCount(0);
  await expect(page.locator(".mode-banner")).toContainText("在线 Agent");
  await page.getByLabel("数据模式").selectOption("mock");
  await expect(page.locator(".message-pair")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "让每个问题都有清晰的落点" }),
  ).toBeVisible();
  expect(apiRequests.length).toBeGreaterThan(0);
});
test("物料筛选、搜索、排序与新建分析", async ({ page }) => {
  await start(page);
  await scenario(page, "production");
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
test("键盘换行、组合输入保护、Enter 发送和帮助弹窗", async ({ page }) => {
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
    page.getByRole("heading", { name: "主板示例库存为 800 件" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "使用说明", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
for (const width of [1440, 1280, 1024, 390, 320]) {
  test(`${width}px 首页与工作台无整页横向溢出，表格局部滚动`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width < 760 ? 844 : 1080 });
    await page.goto("/");
    await noOverflow(page);
    if (width === 1440 || width === 390)
      await page.screenshot({
        path: join(screenshots, `home-${width}.png`),
        fullPage: true,
      });
    if (width < 760) {
      await page.getByRole("button", { name: "打开导航", exact: true }).click();
      await page.getByRole("link", { name: "分析工作台", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "打开导航", exact: true }),
      ).toBeVisible();
    } else
      await page.getByRole("link", { name: "开始分析", exact: true }).click();
    await scenario(page, "production");
    await noOverflow(page);
    if (width < 760)
      expect(
        await page
          .locator(".table-scroll")
          .evaluate((el) => el.scrollWidth > el.clientWidth),
      ).toBe(true);
    await page.screenshot({
      path: join(screenshots, `workspace-${width}.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "查看主板来源", exact: true })
      .click();
    await noOverflow(page);
    await expect(page.getByText("来源发布时间", { exact: true })).toBeVisible();
    if (width === 1440 || width === 390)
      await page.screenshot({
        path: join(screenshots, `sources-${width}.png`),
        fullPage: true,
      });
  });
}
