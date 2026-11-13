import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import {
  API_URL,
  armBrowserSafety,
  expectCleanBrowser,
  harnessRequests,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

// RF-47 / US-41. Sem LLM: o servidor simulado responde de forma determinística.

test.beforeEach(async ({ request }) => resetHarness(request));

async function setAssistantMode(
  request: APIRequestContext,
  mode: "ok" | "forbidden" | "unavailable",
) {
  const response = await request.post(`${API_URL}/__e2e/assistant`, { data: { mode } });
  expect(response.ok()).toBeTruthy();
}

async function openAssistant(page: Page) {
  await page.getByRole("button", { name: "Abrir assistente do sistema" }).click();
  const dialog = page.getByRole("dialog", { name: "Assistente do sistema" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("pergunta autorizada mostra a resposta e só as telas que o painel abre", async ({
  page,
  request,
}) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const dialog = await openAssistant(page);

  await expect(dialog.getByText("Nenhuma pergunta ainda")).toBeVisible();
  const campo = dialog.getByLabel("Sua pergunta");
  await expect(campo).toBeFocused();
  await campo.fill("Onde vejo as pendências de hoje?");
  await dialog.getByRole("button", { name: "Enviar" }).click();

  const conversa = dialog.getByRole("log", { name: "Conversa com o assistente" });
  await expect(conversa.getByText("Onde vejo as pendências de hoje?")).toBeVisible();
  await expect(conversa.getByText("Posso te ajudar com isso.", { exact: false })).toBeVisible();

  // O servidor sugeriu também uma tela admin: o painel não a oferece.
  const telas = conversa.getByRole("list", { name: "Telas sugeridas" });
  await expect(telas.getByRole("link", { name: "Painel de Hoje" })).toBeVisible();
  await expect(telas.getByRole("link")).toHaveCount(1);

  const envios = (await harnessRequests(request)).filter(
    (entry) => entry.method === "POST" && entry.path === "/assistant/message",
  );
  expect(envios).toHaveLength(1);
  expect(envios[0]?.status).toBe(200);
  expect(envios[0]?.body).toEqual({
    tenantId: "00000000-0000-4000-8000-000000000002",
    texto: "Onde vejo as pendências de hoje?",
  });

  // Esc fecha; reabrir mantém o histórico da sessão.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Abrir assistente do sistema" })).toBeFocused();
  const reaberto = await openAssistant(page);
  await expect(reaberto.getByText("Onde vejo as pendências de hoje?")).toBeVisible();

  await reaberto.getByRole("link", { name: "Painel de Hoje" }).click();
  await expect(reaberto).toBeHidden();
  await expect(page).toHaveURL(/#dashboard$/);
  expectCleanBrowser(safety);
});

test("recusa do servidor (403) bloqueia o envio e explica sem expor detalhes", async ({
  page,
  request,
}) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await setAssistantMode(request, "forbidden");
  const dialog = await openAssistant(page);

  await dialog.getByLabel("Sua pergunta").fill("Quero ver tudo");
  await dialog.getByRole("button", { name: "Enviar" }).click();

  await expect(
    dialog.getByText("Seu acesso não permite usar o assistente.", { exact: false }),
  ).toBeVisible();
  await expect(dialog.getByText("tenant não corresponde")).toHaveCount(0);
  await expect(dialog.getByLabel("Sua pergunta")).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Enviar" })).toBeDisabled();
  // O navegador registra a própria resposta 403 como erro de rede; é o único permitido.
  expect(safety.consoleErrors.filter((m) => !m.includes("status of 403"))).toEqual([]);
  safety.consoleErrors.length = 0;
  expectCleanBrowser(safety);
});

test("serviço indisponível (503) mostra erro e permite tentar de novo", async ({
  page,
  request,
}) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await setAssistantMode(request, "unavailable");
  const dialog = await openAssistant(page);

  await dialog.getByLabel("Sua pergunta").fill("Mostre as pendências");
  await dialog.getByRole("button", { name: "Enviar" }).click();
  await expect(dialog.getByRole("alert")).toContainText("indisponível");

  await setAssistantMode(request, "ok");
  await dialog.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(dialog.getByText("Posso te ajudar com isso.", { exact: false })).toBeVisible();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  // A tentativa repetida não duplica a pergunta na conversa.
  await expect(dialog.getByText("Mostre as pendências")).toHaveCount(1);
  // O navegador registra a resposta 503 simulada como erro de rede; é o único permitido.
  expect(safety.consoleErrors.filter((m) => !m.includes("status of 503"))).toEqual([]);
  safety.consoleErrors.length = 0;
  expectCleanBrowser(safety);
});

test("no celular a janela fica acima da barra inferior e o envio continua alcançável", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const dialog = await openAssistant(page);

  await dialog.getByLabel("Sua pergunta").fill("Onde vejo as pendências de hoje?");
  // Sem sobreposição: o clique real chega ao botão (o Playwright falha se algo o cobrir).
  await dialog.getByRole("button", { name: "Enviar" }).click();
  await expect(dialog.getByText("Posso te ajudar com isso.", { exact: false })).toBeVisible();

  const box = await dialog.boundingBox();
  const nav = await page.locator(".bottom-nav").boundingBox();
  expect(box).not.toBeNull();
  if (box && nav) expect(box.y + box.height).toBeGreaterThanOrEqual(nav.y + nav.height - 1);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  expectCleanBrowser(safety);
});
