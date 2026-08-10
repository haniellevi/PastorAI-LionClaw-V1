import { defineConfig, devices } from "@playwright/test";

const appPort = Number(process.env.M09_APP_PORT ?? "3109");
const apiPort = Number(process.env.M09_API_PORT ?? "8009");
const appUrl = `http://127.0.0.1:${appPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    [process.env.CI ? "line" : "list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: appUrl,
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      name: "API mock local",
      command: "node e2e/support/mock-api.mjs",
      url: `${apiUrl}/__e2e/health`,
      env: { M09_API_PORT: String(apiPort), M09_APP_PORT: String(appPort) },
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      name: "Next production local",
      command: `npm run start -- --hostname 127.0.0.1 --port ${appPort}`,
      url: appUrl,
      env: { NEXT_PUBLIC_API_URL: apiUrl },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
