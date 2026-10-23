import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Route } from "@playwright/test";

import {
  API_URL,
  APP_URL,
  armBrowserSafety,
  expectCleanBrowser,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

const cors = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    headers: cors,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
});

test("telas principais atendem WCAG 2.1 A e AA", async ({ page, request }, testInfo) => {
  const safety = await armBrowserSafety(page);

  expect((await request.post(`${API_URL}/__e2e/ux-inbox`)).ok()).toBeTruthy();

  await page.route((url) => url.origin === API_URL && url.pathname === "/contacts", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    await json(route, {
      items: [{
        id: "a11y-person-1",
        nome: "Pessoa Laboratório",
        telefone: "550000000001",
        email: null,
        genero: null,
        tipo: "membro",
        etapa: "consolidar",
        subetapa: null,
        acompanhamento: null,
        semInteresse: false,
        semInteresseMotivo: null,
        presencasCelula: 0,
        aceitouJesus: false,
        celulaId: null,
        liderId: null,
        aptoLider: false,
        liderDeCelula: false,
        arquivada: false,
      }],
      page: 1,
      pageSize: 50,
      total: 1,
    });
  });

  await page.route((url) => url.origin === API_URL && url.pathname === "/team", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    await json(route, {
      items: [{
        usuarioId: "00000000-0000-4000-8000-000000000001",
        pessoaId: null,
        nome: "Admin E2E",
        email: "admin.e2e@example.test",
        status: "ativo",
        papeis: ["admin", "pastor"],
      }],
      total: 1,
      page: 1,
      pageSize: 50,
    });
  });

  await page.route((url) => url.origin === API_URL && url.pathname.startsWith("/conhecimento/"), async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    await json(route, { pode_criar: true, responsavel_id: "a11y-user", documentos: [] });
  });

  await loginThroughUi(page);

  const screens = [
    {
      id: "hoje",
      path: "/#dashboard",
      heading: page.locator(".dashboard .dh-title"),
      ready: () => expect(page.getByText("Acompanhar visitante E2E", { exact: true })).toBeVisible(),
    },
    {
      id: "atendimento",
      path: "/#inbox",
      heading: page.locator(".ib-head h2"),
      ready: () => expect(page.getByText("Contato A", { exact: true })).toBeVisible(),
    },
    {
      id: "contatos",
      path: "/gestao/#contatos",
      heading: page.locator(".people-screen .screen-head h2"),
      ready: async () => {
        await expect(page.locator(".people-list-region[aria-busy]")).toHaveAttribute("aria-busy", "false");
        await expect(page.getByRole("main").getByText("Pessoa Laboratório", { exact: true })).toBeVisible();
      },
    },
    {
      id: "equipe",
      path: "/gestao/#equipe",
      heading: page.getByRole("heading", { name: "Pessoas com acesso", exact: true }),
      ready: () => expect(page.getByRole("main").getByText("Admin E2E", { exact: true })).toBeVisible(),
    },
    {
      id: "agenda",
      path: "/#calendario",
      heading: page.locator(".agenda .screen-head h2"),
      ready: () => expect(page.locator(".agenda-empty")).toBeVisible(),
    },
    {
      id: "conhecimento",
      path: "/#conhecimento",
      heading: page.locator(".conhecimento-screen .screen-head h2"),
      ready: async () => {
        await expect(page.locator(".conhecimento-screen")).toHaveAttribute("aria-busy", "false");
        await expect(page.getByText("Nenhum documento disponível para seu acesso.", { exact: true })).toBeVisible();
      },
    },
  ];
  const violations: Array<Record<string, unknown>> = [];

  for (const screen of screens) {
    await page.goto(screen.path);
    await expect(screen.heading, `tela ${screen.id} carregada`).toBeVisible();
    await screen.ready();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const screenViolations = results.violations.map((violation) => ({
      screen: screen.id,
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      helpUrl: violation.helpUrl,
      nodes: violation.nodes.map((node) => ({
        target: node.target,
        summary: node.failureSummary,
      })),
    }));

    violations.push(...screenViolations);
    await testInfo.attach(`axe-${screen.id}`, {
      body: Buffer.from(JSON.stringify(screenViolations, null, 2)),
      contentType: "application/json",
    });
  }

  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
  expectCleanBrowser(safety);
});
