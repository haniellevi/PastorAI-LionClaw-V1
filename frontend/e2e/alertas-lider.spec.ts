import { expect, test, type Page } from "@playwright/test";
import {
  API_URL,
  APP_URL,
  armBrowserSafety,
  expectCleanBrowser,
  harnessRequests,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

// RF-26. Identidades, regras e alertas são sintéticos; nenhum provedor externo.

async function actAsLeader(page: Page) {
  await page.route(`${API_URL}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET" && path === "/auth/me") {
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": APP_URL, "Cache-Control": "no-store" },
        contentType: "application/json",
        body: JSON.stringify({
          appUserId: "00000000-0000-4000-8000-000000000001",
          churchId: "00000000-0000-4000-8000-000000000002",
          email: "lider.e2e@example.test",
          nome: "Líder de exemplo",
          chatNome: "Líder",
          roles: ["lider_celula"],
          isOwner: false,
          igrejaNome: "Igreja Laboratório",
          igrejaLogoUrl: null,
        }),
      });
      return;
    }
    if (request.method() === "GET" && /^\/cells\/[^/]+\/reunioes$/.test(path)) {
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": APP_URL, "Cache-Control": "no-store" },
        contentType: "application/json",
        body: "[]",
      });
      return;
    }
    if (request.method() === "GET" && path === "/cells/me/leading") {
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": APP_URL, "Cache-Control": "no-store" },
        contentType: "application/json",
        body: JSON.stringify([{ id: "00000000-0000-4000-8000-000000000020", nome: "Célula E2E" }]),
      });
      return;
    }
    if (request.method() === "GET" && path === "/roles/permissions") {
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": APP_URL, "Cache-Control": "no-store" },
        contentType: "application/json",
        body: JSON.stringify({ matriz: { lider_celula: ["dashboard", "minha-celula"] } }),
      });
      return;
    }
    await route.fallback();
  });
  await page.reload();
}

test.beforeEach(async ({ request }) => resetHarness(request));

test("admin liga e ajusta uma regra de alerta ao líder", async ({ page, request }) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await page.goto("/gestao/#alertas-lider");
  await expect(
    page.getByRole("heading", { level: 2, name: "Alertas ao líder", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("ainda não foi liberada", { exact: false })).toBeVisible();

  const form = page.getByRole("form", { name: "Relatório de célula pendente" });
  await expect(form.getByText("Regra desligada")).toBeVisible();
  await form.getByText("Regra desligada").locator("..").locator(".switch").click();
  await expect(form.getByText("Regra ligada")).toBeVisible();

  const hours = form.getByLabel("Avisar depois de (horas)");
  await hours.fill("0");
  await form.getByRole("button", { name: "Salvar regra" }).click();
  // Validação nativa do campo (min/max) barra o envio antes do servidor.
  expect(await hours.evaluate((el: HTMLInputElement) => el.checkValidity())).toBe(false);
  expect((await harnessRequests(request)).some((entry) => entry.method === "PUT")).toBe(false);

  await hours.fill("48");
  await form.getByRole("button", { name: "Salvar regra" }).click();
  await expect(form.getByRole("status").filter({ hasText: "Regra salva." })).toBeVisible();

  const puts = (await harnessRequests(request)).filter(
    (entry) => entry.method === "PUT" && entry.path === "/cell-alert-rules/relatorio_pendente",
  );
  expect(puts).toHaveLength(1);
  expect(puts[0]?.body).toEqual({ ativo: true, parametros: { horas_apos_reuniao: 48 } });

  await page.reload();
  const reloaded = page.getByRole("form", { name: "Relatório de célula pendente" });
  await expect(reloaded.getByText("Regra ligada")).toBeVisible();
  await expect(reloaded.getByLabel("Avisar depois de (horas)")).toHaveValue("48");
  expectCleanBrowser(safety);
});

test("líder vê e trata alerta da sua célula em Hoje; não acessa as regras", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await actAsLeader(page);

  const panel = page.getByRole("region", { name: "Alertas da sua célula" });
  await expect(panel.getByText("Relatório de célula pendente")).toBeVisible();
  await expect(panel.getByText("Célula E2E", { exact: false }).first()).toBeVisible();

  // Dois alertas do mesmo gatilho, de pessoas diferentes, ficam distinguíveis.
  const consolidacao = panel.locator("article").filter({ hasText: "Liderado em consolidação" });
  await expect(consolidacao).toHaveCount(2);
  await expect(consolidacao.filter({ hasText: "Ana Exemplo" })).toHaveCount(1);
  await expect(consolidacao.filter({ hasText: "Bruno Exemplo" })).toHaveCount(1);

  await panel
    .locator("article")
    .filter({ hasText: "Relatório de célula pendente" })
    .getByRole("button", { name: "Tratar" })
    .click();
  await expect(panel.getByText("Relatório de célula pendente")).toHaveCount(0);
  await expect(panel.locator("article")).toHaveCount(2);

  const requests = await harnessRequests(request);
  expect(
    requests.filter(
      (entry) =>
        entry.method === "POST" &&
        entry.path ===
          "/cells/00000000-0000-4000-8000-000000000020/alerts/00000000-0000-4000-8000-0000000000a1/baixar",
    ),
  ).toHaveLength(1);

  // Recusa: a superfície de regras é só do admin.
  await page.goto("/gestao/#alertas-lider");
  await expect(page.getByRole("button", { name: "Salvar regra" })).toHaveCount(0);
  const after = await harnessRequests(request);
  expect(after.some((entry) => entry.path === "/cell-alert-rules")).toBe(false);
  expectCleanBrowser(safety);
});
