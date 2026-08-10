import { defineConfig, devices } from "@playwright/test";

import { resolveM09Urls } from "./e2e/support/loopback-url.mjs";

const { app, api } = resolveM09Urls();
const appUrl = app.origin;
const apiUrl = api.origin;

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
      env: { M09_API_URL: apiUrl, M09_APP_URL: appUrl },
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      name: "Next production local",
      command: `npm run start -- --hostname ${app.hostname} --port ${app.port}`,
      url: appUrl,
      env: { NEXT_PUBLIC_API_URL: apiUrl, M09_API_URL: apiUrl, M09_APP_URL: appUrl },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
