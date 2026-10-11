import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./review-tests",
  outputDir: process.env.PMC_REVIEW_E2E_OUTPUT || "../../.runtime/review-browser-results",
  reporter: [["list"], ["json", {outputFile: (process.env.PMC_REVIEW_E2E_OUTPUT || "../../.runtime/review-browser-results") + "/browser-evidence.json"}]],
  workers: 1,
  timeout: 60000,
  expect: { timeout: 10000 },
  use: {
    baseURL: "http://127.0.0.1:8090",
    channel: "msedge",
    httpCredentials: { username: process.env.PMC_E2E_USER_A ?? "review-a", password: process.env.PMC_E2E_PASSWORD! },
  },
});
