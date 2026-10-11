import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [vue()],
    build: process.env.PMC_TRIAL_BUILD_OUT
      ? { outDir: process.env.PMC_TRIAL_BUILD_OUT, emptyOutDir: false }
      : undefined,
    define: {
      "import.meta.env.VITE_API_BASE_URL": JSON.stringify(
        env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
      ),
    },
    server: { port: 5173, strictPort: true },
  };
});
