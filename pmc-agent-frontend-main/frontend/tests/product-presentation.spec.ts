import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope, session } from "./agentFixtures";

test("智能查询默认收起、点选收起、新会话及刷新保持紧凑，窄屏不溢出", async ({page}) => {
  let calls = 0;
  await page.route("**/api/v1/agent/catalog", r => r.fulfill({json:{products:[{
    product_code:"EXAMPLE-A", synthetic:false, default_mode:"full",
    modes:[{mode:"full",label:"完整追溯范围",scenario_id:null,line_count:66,dataset_version:null}],
  }]}}));
  await page.route("**/api/v1/agent/sessions", r => r.fulfill({json:session}));
  await page.route("**/api/v1/agent/query", r => {
    calls++;
    return r.fulfill({json:{...envelope("fact_query", {products:[]}),session_id:session.session_id}});
  });
  await page.goto("/#/workspace");
  const toggle = page.getByRole("button", {name:"展开推荐问题"});
  await expect(toggle).toHaveAttribute("aria-expanded","false");
  await expect(page.locator(".quick-questions")).toHaveCount(0);
  const closed = (await page.locator(".smart-queries").boundingBox())!.height;
  await toggle.click();
  await expect(page.getByRole("button", {name:"收起",exact:true})).toHaveAttribute("aria-expanded","true");
  expect((await page.locator(".smart-queries").boundingBox())!.height).toBeGreaterThan(closed);
  await page.locator(".quick-questions").getByRole("button", {name:"查看BOM"}).click();
  await expect(toggle).toBeVisible();
  await expect(page.locator(".assistant-message")).toHaveCount(1);
  expect(calls).toBe(1);
  await page.getByRole("button", {name:"新建分析",exact:true}).click();
  await expect(toggle).toHaveAttribute("aria-expanded","false");
  await page.setViewportSize({width:390,height:844});
  await toggle.click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-expanded","false");
});
