import { expect, test } from "@playwright/test";

import {
  armBrowserSafety,
  attachJson,
  attachM09OutcomeSnapshot,
  expectDashboardContextReady,
  expectCleanBrowser,
  harnessRequests,
  LOCAL_TOKEN,
  loginThroughUi,
  percentile75,
  resetHarness,
  resourceTimeline,
} from "./support/helpers";

const DASHBOARD_PATHS = [
  "/work-queue",
  "/team/lookup",
  "/cells",
  "/dashboard/overview",
];

function dashboardRequests(
  requests: Awaited<ReturnType<typeof harnessRequests>>,
) {
  return requests.filter((entry) => DASHBOARD_PATHS.includes(entry.path));
}

function expectParallelDashboardReads(
  requests: Awaited<ReturnType<typeof harnessRequests>>,
): void {
  const reads = dashboardRequests(requests);
  expect(reads).toHaveLength(4);
  const starts = reads.map((entry) => entry.startedAt);
  expect(Math.max(...starts) - Math.min(...starts)).toBeLessThan(100);
}

test.afterEach(async ({ page, request }, testInfo) => {
  await attachM09OutcomeSnapshot(page, request, testInfo);
});

test.describe("M09 · gates críticos locais e sem efeitos externos", () => {
  test("login novo dá feedback imediato e carrega o dashboard sem /auth/me", async ({
    page,
    request,
  }, testInfo) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);

    const metrics = await loginThroughUi(page);
    const requests = await harnessRequests(request);
    const auth = requests.find(
      (entry) => entry.method === "POST" && entry.path === "/auth/login",
    );
    expect(auth).toBeDefined();
    expect(requests.some((entry) => entry.path === "/auth/me")).toBe(false);
    expectParallelDashboardReads(requests);

    const firstDashboardStart = Math.min(
      ...dashboardRequests(requests).map((entry) => entry.startedAt),
    );
    expect(firstDashboardStart).toBeGreaterThanOrEqual((auth?.finishedAt ?? 0) - 10);
    expect(metrics.feedbackMs).toBeLessThan(500);
    expect(metrics.dashboardCompleteMs).toBeLessThan(4_000);
    expectCleanBrowser(safety);

    await attachJson(testInfo, "fresh-login-baseline", {
      metrics,
      requests,
      resources: await resourceTimeline(page),
      browserSafety: safety,
    });
  });

  test("sessão restaurada valida /auth/me antes dos dados e preserva leituras paralelas", async ({
    page,
    request,
  }, testInfo) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);
    await page.addInitScript((token) => {
      window.localStorage.setItem("pastorai:token", token);
    }, LOCAL_TOKEN);

    const startedAt = Date.now();
    await page.goto("/#dashboard", { waitUntil: "domcontentloaded" });
    await expectDashboardContextReady(page);
    const dashboardCompleteMs = Date.now() - startedAt;

    const requests = await harnessRequests(request);
    const auth = requests.find(
      (entry) => entry.method === "GET" && entry.path === "/auth/me",
    );
    expect(auth).toBeDefined();
    expect(requests.some((entry) => entry.path === "/auth/login")).toBe(false);
    expectParallelDashboardReads(requests);
    const firstDashboardStart = Math.min(
      ...dashboardRequests(requests).map((entry) => entry.startedAt),
    );
    expect(firstDashboardStart).toBeGreaterThanOrEqual((auth?.finishedAt ?? 0) - 10);
    expect(dashboardCompleteMs).toBeLessThan(4_000);
    expectCleanBrowser(safety);

    await attachJson(testInfo, "restored-session-baseline", {
      dashboardCompleteMs,
      requests,
      resources: await resourceTimeline(page),
      browserSafety: safety,
    });
  });

  test("navegação aquecida mantém feedback imediato e p75 completo abaixo de 1 s", async ({
    page,
    request,
  }, testInfo) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);

    const agenda = page.getByRole("button", { name: "Agenda" });
    const dashboard = page.getByRole("button", { name: "Painel de Hoje" });

    // Aquecimento explícito: pointer/hover dispara chunk + dados, depois a tela
    // é visitada uma vez antes das amostras que entram no p75.
    await agenda.hover();
    await agenda.click();
    await expect(page.getByText(/^Nenhum evento em /)).toBeVisible();
    await dashboard.click();
    await expectDashboardContextReady(page);

    const samples: Array<{ feedbackMs: number; completeMs: number }> = [];
    for (let index = 0; index < 8; index += 1) {
      const started = await page.evaluate(() => performance.now());
      await agenda.click();
      await expect(page.getByRole("heading", { name: "Agenda da Igreja" })).toBeVisible();
      const feedbackAt = await page.evaluate(() => performance.now());
      await expect(page.getByText(/^Nenhum evento em /)).toBeVisible();
      const completeAt = await page.evaluate(() => performance.now());
      samples.push({
        feedbackMs: feedbackAt - started,
        completeMs: completeAt - started,
      });

      await dashboard.click();
      await expectDashboardContextReady(page);
    }

    const feedbackP75 = percentile75(samples.map((sample) => sample.feedbackMs));
    const completeP75 = percentile75(samples.map((sample) => sample.completeMs));
    expect(feedbackP75).toBeLessThan(250);
    expect(completeP75).toBeLessThan(1_000);
    expectCleanBrowser(safety);
    await attachJson(testInfo, "warm-navigation-baseline", {
      samples,
      feedbackP75,
      completeP75,
      browserSafety: safety,
    });
  });

  test("troca de modelo usa apenas o mock local e confirma o PUT esperado", async ({
    page,
    request,
  }, testInfo) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    await page.goto("/gestao#agente", { waitUntil: "domcontentloaded" });

    await expect(page.getByText("Credencial ativa")).toBeVisible();
    await page.getByRole("button", { name: "Credencial LLM" }).click();
    await page.getByLabel("Modelo").selectOption("gpt-5.6-terra");
    await page.getByRole("button", { name: "Salvar modelo" }).click();
    await expect(page.getByText("Modelo validado e atualizado.")).toBeVisible();

    const requests = await harnessRequests(request);
    const updates = requests.filter(
      (entry) => entry.method === "PUT" && entry.path === "/agent/model",
    );
    expect(updates).toHaveLength(1);
    expect(updates[0]?.body).toEqual({ modelo: "gpt-5.6-terra" });
    expectCleanBrowser(safety);
    await attachJson(testInfo, "model-switch-evidence", {
      requests: updates,
      browserSafety: safety,
    });
  });

  test("conexão WhatsApp gera QR somente no mock local", async ({
    page,
    request,
  }, testInfo) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    await page.goto("/gestao#whatsapp", { waitUntil: "domcontentloaded" });

    await expect(page.getByText("Número desconectado")).toBeVisible();
    await page.getByRole("button", { name: "Conectar (ler QR code)" }).click();
    await expect(
      page.getByRole("img", {
        name: "QR code de conexão — leia no WhatsApp do número oficial",
      }),
    ).toBeVisible();
    await expect(page.getByText("Conexão iniciada.")).toBeVisible();

    const requests = await harnessRequests(request);
    const connects = requests.filter(
      (entry) => entry.method === "POST" && entry.path === "/whatsapp/connection",
    );
    expect(connects).toHaveLength(1);
    expect(connects[0]?.body).toEqual({ action: "connect" });
    expectCleanBrowser(safety);
    await attachJson(testInfo, "whatsapp-local-evidence", {
      requests: connects,
      browserSafety: safety,
    });
  });
});
