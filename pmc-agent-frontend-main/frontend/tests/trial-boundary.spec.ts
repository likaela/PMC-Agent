import { test, expect } from "@playwright/test";
import { isAllowedScenario } from "../trial/scenarioPolicy";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

test("纯合成策略只接受唯一公开场景", () => {
  expect(isAllowedScenario("demo_scenario_50_vs_100")).toBe(true);
  for (const value of [null, "enterprise", "private-scene", {}]) expect(isAllowedScenario(value)).toBe(false);
});

test("生产试用构建依赖不包含企业入口、场景表、mock或静态企业资源", () => {
  mkdirSync(resolve("../../.runtime"), { recursive: true });
  const output = mkdtempSync(resolve("../../.runtime/trial-build-test-"));
  execFileSync(process.execPath, ["node_modules/vite/bin/vite.js", "build"], {
    env: { ...process.env, PMC_TRIAL_BUILD_OUT: output }, timeout: 30000,
  });
  const modules = JSON.parse(readFileSync(resolve(output, "module-closure.json"), "utf8")) as string[];
  expect(modules).toContain("trial/useTrialAgent.ts");
  expect(modules).toContain("trial/scenarioPolicy.ts");
  expect(modules.some(m => /App\.vue$/.test(m) && !m.startsWith("trial/"))).toBe(false);
  expect(modules.some(m => /src\/(composables|views)|sessionStorage|fixtures|mockService|src\/services\/scenarioPolicy/.test(m))).toBe(false);
  const assets = readdirSync(resolve(output, "assets"));
  expect(assets.some(name => name.endsWith(".map"))).toBe(false);
  const text = assets.map(name => readFileSync(resolve(output, "assets", name), "utf8")).join("\n") + readFileSync(resolve(output, "index.html"), "utf8");
  expect(text).not.toMatch(/KQ-|kq_z112|review_real_bom_simulation|data[\\/]raw|[CE]:[\\/]/i);
  expect(text).toContain("DEMO-PMC-01");
});
