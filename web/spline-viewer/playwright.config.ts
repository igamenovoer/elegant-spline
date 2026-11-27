import { defineConfig } from "@playwright/test";

const baseURL = "http://127.0.0.1:4187";

export default defineConfig({
  testDir: "./tests/e2e",
  use: { baseURL, browserName: "chromium" },
  webServer: {
    command: "bun run build && bun ./tests/serve-dist.ts",
    url: baseURL,
    reuseExistingServer: false,
  },
});
