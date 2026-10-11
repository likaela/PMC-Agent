import {defineConfig} from "@playwright/test";
export default defineConfig({testDir:"./workstation-tests", outputDir:"../../.runtime/workstation-browser-results",
  workers:1, timeout:60000, expect:{timeout:10000}, use:{baseURL:"http://127.0.0.1:5173", channel:"msedge"}});
