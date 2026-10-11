import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

test("授权评审构建仅依赖API目录，不包含静态企业数据或本地场景入口", () => {
  mkdirSync(resolve("../../.runtime"), { recursive: true });
  const output = mkdtempSync(resolve("../../.runtime/review-build-test-"));
  const env: NodeJS.ProcessEnv = { ...process.env, PMC_REVIEW_BUILD_OUT: output };
  delete env.PMC_TRIAL_BUILD_OUT;
  execFileSync(process.execPath, ["node_modules/vite/bin/vite.js", "build"], { env, timeout: 30000 });
  const modules = JSON.parse(readFileSync(resolve(output, "module-closure.json"), "utf8")) as string[];
  expect(modules).toContain("review/useReviewAgent.ts");
  expect(modules).toContain("review/reviewClient.ts");
  expect(modules.some(m => /src\/(composables|views)|fixtures|mockService|src\/services\/scenarioPolicy|trial\//.test(m))).toBe(false);
  const assets = readdirSync(resolve(output, "assets"));
  expect(assets.some(name => name.endsWith(".map"))).toBe(false);
  const text = assets.map(name => readFileSync(resolve(output, "assets", name), "utf8")).join("\n") + readFileSync(resolve(output, "index.html"), "utf8");
  expect(text).not.toMatch(/KQ-|kq_z112|review_real_bom_simulation|data[\\/]raw|[CE]:[\\/]/i);
  expect(text).toContain("/api/v1/review/catalog");
  expect(text).toContain("/api/v1/agent/query");
});
