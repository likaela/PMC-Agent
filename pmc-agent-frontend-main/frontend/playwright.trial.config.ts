import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./trial-tests",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:8080",
    channel: "msedge",
    httpCredentials: {
      username: "trial-a",
      password: process.env.PMC_E2E_PASSWORD!,
    },
  },
});
