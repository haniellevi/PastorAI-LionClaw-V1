import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { resolveM09Urls } from "./loopback-url.mjs";

const M09_URLS = resolveM09Urls();
export const API_URL = M09_URLS.api.origin;
export const APP_URL = M09_URLS.app.origin;
export const LOCAL_TOKEN = "m09-local-e2e-token";
export const SOURCE_SHA =
  process.env.GITHUB_SHA ??
  execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: path.resolve(process.cwd(), ".."),
    encoding: "utf8",
  }).trim();
export const E2E_USER = {
  email: "admin.e2e@example.test",
  password: "local-only",
};

export interface HarnessRequest {
  id: number;
  method: string;
  path: string;
  query: string;
  startedAt: number;
  finishedAt: number;
  durationMs: number;
  status: number;
  body: unknown;
}

export interface BrowserSafety {
  consoleErrors: string[];
  pageErrors: string[];
  externalRequests: string[];
}

export interface LoginMetrics {
  feedbackMs: number;
  dashboardCompleteMs: number;
}

export async function resetHarness(request: APIRequestContext): Promise<void> {
  const response = await request.post(`${API_URL}/__e2e/reset`);
  expect(response.ok()).toBeTruthy();
}

export async function harnessRequests(
  request: APIRequestContext,
): Promise<HarnessRequest[]> {
  const response = await request.get(`${API_URL}/__e2e/requests`);
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { requests: HarnessRequest[] };
  return body.requests;
}

/**
 * Bloqueia qualquer origem externa antes da primeira navegação. Assim, mesmo
 * um link/asset introduzido por engano não pode gerar efeito fora do lab M09.
 */
export async function armBrowserSafety(page: Page): Promise<BrowserSafety> {
  const safety: BrowserSafety = {
    consoleErrors: [],
    pageErrors: [],
    externalRequests: [],
  };

  page.on("console", (message) => {
    if (message.type() === "error") safety.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => safety.pageErrors.push(error.message));
  const allowedOrigins = new Set([new URL(APP_URL).origin, new URL(API_URL).origin]);
  await page.route("**/*", async (route) => {
    const target = new URL(route.request().url());
    if (
      allowedOrigins.has(target.origin) ||
      target.protocol === "data:" ||
      target.protocol === "blob:"
    ) {
      await route.continue();
      return;
    }
    safety.externalRequests.push(target.href);
    await route.abort("blockedbyclient");
  });
  return safety;
}

export function expectCleanBrowser(safety: BrowserSafety): void {
  expect(safety.externalRequests, "requisições externas bloqueadas").toEqual([]);
  expect(safety.pageErrors, "erros JavaScript não tratados").toEqual([]);
  expect(safety.consoleErrors, "console.error no navegador").toEqual([]);
}

export async function loginThroughUi(page: Page): Promise<LoginMetrics> {
  await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entrar no painel" })).toBeVisible();
  await page.getByLabel("E-mail").fill(E2E_USER.email);
  await page.getByRole("textbox", { name: "Senha", exact: true }).fill(E2E_USER.password);

  const startedAt = await page.evaluate(() => performance.now());
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("button", { name: "Autenticando…" })).toBeVisible({
    timeout: 500,
  });
  const feedbackAt = await page.evaluate(() => performance.now());

  await expect(page.getByText("Acompanhar visitante E2E")).toBeVisible();
  const dashboardAt = await page.evaluate(() => performance.now());
  return {
    feedbackMs: feedbackAt - startedAt,
    dashboardCompleteMs: dashboardAt - startedAt,
  };
}

export async function resourceTimeline(page: Page) {
  const apiOrigin = new URL(API_URL).origin;
  return page.evaluate(
    (allowedApiOrigin) =>
      performance
        .getEntriesByType("resource")
        .map((entry) => {
          const resource = entry as PerformanceResourceTiming;
          return {
            name: resource.name,
            initiatorType: resource.initiatorType,
            startTime: Math.round(resource.startTime * 10) / 10,
            responseEnd: Math.round(resource.responseEnd * 10) / 10,
            duration: Math.round(resource.duration * 10) / 10,
          };
        })
        .filter(
          (entry) =>
            entry.name.includes("/_next/") ||
            entry.name.startsWith(allowedApiOrigin),
        ),
    apiOrigin,
  );
}

export async function attachJson(
  testInfo: TestInfo,
  name: string,
  value: unknown,
): Promise<void> {
  const evidence = {
    sourceSha: SOURCE_SHA,
    generatedAt: new Date().toISOString(),
    node: process.version,
    value,
  };
  const body = `${JSON.stringify(evidence, null, 2)}\n`;
  await testInfo.attach(name, {
    body: Buffer.from(body, "utf8"),
    contentType: "application/json",
  });
  const metricsDir = path.join(process.cwd(), "test-results", "metrics");
  await mkdir(metricsDir, { recursive: true });
  await writeFile(path.join(metricsDir, `${name}.json`), body, "utf8");
}

export function percentile75(values: number[]): number {
  if (values.length === 0) throw new Error("p75 exige ao menos uma amostra");
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil(sorted.length * 0.75) - 1]!;
}
