import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  use: { baseURL: process.env.DASHBOARD_URL ?? "http://127.0.0.1:3000", trace: "retain-on-failure" },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVERS
    ? undefined
    : [
        {
          command: ".\\.venv\\Scripts\\python.exe -m uvicorn evaluation_service.app:app --host 127.0.0.1 --port 8000",
          cwd: "../..",
          port: 8000,
          reuseExistingServer: true,
          timeout: 120_000,
          env: {
            FRONTIER_DATABASE_PATH: ".frontier/playwright.sqlite3",
            TALON_DATA_DIR: ".frontier/playwright-talon",
            TALON_DATABASE_PATH: ".frontier/playwright-talon/talon.sqlite3",
          },
        },
        { command: "npm run dev -- --hostname 127.0.0.1 --port 3000", port: 3000, reuseExistingServer: true, timeout: 120_000 },
      ],
});
