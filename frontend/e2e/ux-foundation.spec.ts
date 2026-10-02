import { expect, test, type Route } from "@playwright/test";
import { API_URL, APP_URL, armBrowserSafety, attachJson, expectCleanBrowser, loginThroughUi, resetHarness } from "./support/helpers";

const cors = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, headers: cors, contentType: "application/json", body: JSON.stringify(body) });
}

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
  expect((await request.post(`${API_URL}/__e2e/ux-inbox`)).ok()).toBeTruthy();
});

test("navegação mantém destinos reais, foco e retorno do menu mobile", async ({ page }, testInfo) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const nav = page.getByRole("navigation", { name: "Menu principal", exact: true });
  const link = nav.getByRole("link", { name: "Conversas", exact: true });
  await expect(link).toHaveAttribute("href", "#inbox");
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Conversas", level: 1 })).toBeVisible();
  await expect(page.locator("#main-content")).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  const more = page.getByRole("button", { name: /Mais.*abrir menu/ });
  await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(more).toBeFocused();
  await expect(more).toHaveAttribute("aria-expanded", "false");
  const cdp = await page.context().newCDPSession(page);
  const tree = await cdp.send("Accessibility.getFullAXTree");
  const landmarks = tree.nodes.filter((node) => ["main", "navigation", "heading"].includes(String(node.role?.value)))
    .map((node) => ({ role: node.role?.value, name: node.name?.value }));
  expect(landmarks.some((node) => node.role === "main")).toBeTruthy();
  expect(landmarks.some((node) => node.name === "Navegação rápida")).toBeTruthy();
  await attachJson(testInfo, "accessibility-landmarks", landmarks);
  expectCleanBrowser(safety);
});

for (const legal of ["termos", "privacidade"]) {
  test(`leitura de ${legal} mantém conteúdo, links, teclado e ampliação CSS`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(`/${legal}`);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.locator("article h2").first()).toBeVisible();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("link", { name: "Ir para o conteúdo", exact: true })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.locator("#conteudo-legal")).toBeFocused();
      await page.getByText("Localizar seção", { exact: true }).click();
      const firstSection = page.getByRole("navigation", { name: "Seções deste documento" }).getByRole("link").first();
      const href = await firstSection.getAttribute("href");
      expect(href).toMatch(/^#[a-z-]+$/);
      await firstSection.click();
      await expect(page).toHaveURL(new RegExp(`${href}$`));
      await expect(page.locator(`article h2${href}`)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      await page.screenshot({ path: testInfo.outputPath(`${legal}-${width}.png`), fullPage: true });
    }
    // Ampliação do layout por CSS é uma checagem de reflow, não prova do zoom
    // nativo do navegador nem da experiência de um leitor de tela instalado.
    await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(page.getByRole("link", { name: "Entrar no painel", exact: true })).toBeVisible();
    expectCleanBrowser(safety);
  });
}

test("falha no envio preserva texto, sem repetição automática, e aceita anexo sintético", async ({ page }, testInfo) => {
  const safety = await armBrowserSafety(page);
  let submissions = 0;
  await page.route(`${API_URL}/conversations/ux-conversation-1/messages`, async (route) => {
    if (route.request().method() !== "POST") { await route.fallback(); return; }
    submissions += 1;
    await json(route, 422, { detail: "Resposta recusada pelo cenário sintético." });
  });
  await page.route(`${API_URL}/conversations/ux-conversation-1/messages/media`, async (route) => {
    if (route.request().method() === "OPTIONS") { await route.fulfill({ status: 204, headers: cors }); return; }
    const body = route.request().postDataJSON() as { mime: string; nome: string; caption: string };
    expect(body.mime).toBe("text/plain");
    expect(body.nome).toBe("anexo-sintetico.txt");
    await json(route, 200, { id: "midia-sintetica", direcao: "out", autor: "humano", autorNome: "Admin E2E", tipo: "arquivo",
      texto: body.caption, mediaUrl: null, mediaMime: body.mime, mediaNome: body.nome, criadoEm: "2026-10-01T20:00:00Z" });
  });
  await loginThroughUi(page);
  await page.goto("/#inbox");
  await page.locator(".conv").filter({ has: page.getByText("Contato B", { exact: true }) }).click();
  const input = page.getByRole("textbox", { name: "Resposta ao contato" });
  await input.fill("Texto sintético preservado");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.locator(".ds-toast--err")).toContainText("Seu texto foi preservado");
  await expect(input).toHaveValue("Texto sintético preservado");
  expect(submissions).toBe(1);
  await page.locator('.thread-foot input[type="file"]').setInputFiles({ name: "anexo-sintetico.txt", mimeType: "text/plain", buffer: Buffer.from("Conteúdo sintético sem dados pessoais") });
  await expect(page.getByRole("button", { name: "Remover anexo" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("atendimento-anexo.png"), fullPage: true });
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remover anexo" })).toHaveCount(0);
  expect(submissions).toBe(1);
  expect(safety.externalRequests).toEqual([]);
  expect(safety.pageErrors).toEqual([]);
  expect(safety.consoleErrors.filter((message) => !message.includes("status of 422"))).toEqual([]);
});

test("conflito remoto anuncia o responsável e bloqueia assumir e compor", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await page.route(`${API_URL}/conversations/ux-conversation-0/handoff`, async (route) => {
    if (route.request().method() === "OPTIONS") { await route.fulfill({ status: 204, headers: cors }); return; }
    await json(route, 409, { detail: { message: "Atendimento assumido por outro responsável.", estado: "humano", assumidoPor: "responsavel-sintetico" } });
  });
  await loginThroughUi(page);
  await page.goto("/#inbox");
  await page.getByRole("button", { name: "Assumir atendimento", exact: true }).click();
  await expect(page.getByRole("button", { name: "Assumir atendimento", exact: true })).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "Resposta ao contato" })).toBeDisabled();
  await expect(page.locator(".ib-banners")).toContainText("Atendimento assumido por outro responsável.");
  expect(safety.externalRequests).toEqual([]);
  expect(safety.pageErrors).toEqual([]);
  expect(safety.consoleErrors.filter((message) => !message.includes("status of 409"))).toEqual([]);
});
