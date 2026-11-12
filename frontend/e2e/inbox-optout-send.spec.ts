import { expect, test } from "@playwright/test";
import {
  API_URL,
  APP_URL,
  armBrowserSafety,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

// B4 (decisão de 12/11/2026): o envio humano pelo painel obedece ao opt-out
// global. O backend recusa com 409 e um motivo claro; o atendente vê o motivo
// e o texto digitado é preservado. Contato sem opt-out recebe normalmente.
const OPTOUT_DETAIL =
  "Este contato pediu para não receber mensagens (opt-out). O envio foi bloqueado. " +
  "Só um admin ou pastor pode reativar as comunicações em Contatos, e apenas se a própria pessoa pedir.";
const USER_ID = "00000000-0000-4000-8000-000000000001";
const headers = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
};

const conversation = (id: string, nome: string) => ({
  id,
  telefone: "5500000000000",
  nome,
  pessoaId: null,
  estado: "humano",
  ultimaMensagem: "Olá",
  naoLidas: 0,
  assumidoPor: USER_ID,
  assumidoPorNome: "Você",
  semInteresse: false,
});

test("envio humano: contato sem opt-out recebe e contato em opt-out é bloqueado com motivo", async ({
  page,
  request,
}) => {
  await resetHarness(request);
  await request.post(`${API_URL}/__e2e/ux-inbox`);
  const safety = await armBrowserSafety(page);
  const sent: string[] = [];
  await page.route(`${API_URL}/conversations**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    let status = 200;
    let body: unknown;
    if (path === "/conversations")
      body = {
        items: [
          conversation("conv-allowed", "Contato liberado fictício"),
          conversation("conv-optout", "Contato em opt-out fictício"),
        ],
        page: 1,
        pageSize: 100,
        total: 2,
      };
    else if (path.endsWith("/photo")) body = { url: null };
    else if (path.endsWith("/read")) {
      await route.fulfill({ status: 204, headers });
      return;
    } else if (path.endsWith("/messages") && method === "POST") {
      const texto = (route.request().postDataJSON() as { texto: string }).texto;
      if (path.includes("conv-optout")) {
        status = 409;
        body = { detail: OPTOUT_DETAIL };
      } else {
        sent.push(texto);
        body = {
          id: "sent-1",
          tipo: "texto",
          direcao: "out",
          autor: "humano",
          autorNome: "Você",
          texto,
          mediaUrl: null,
          mediaMime: null,
          mediaNome: null,
          criadoEm: "2026-11-12T12:00:00Z",
        };
      }
    } else if (path.endsWith("/messages")) {
      body = {
        items: [],
        page: 1,
        pageSize: 50,
        total: 0,
        nextBefore: null,
        nextAfter: null,
      };
    } else {
      await route.fallback();
      return;
    }
    await route.fulfill({ status, headers, contentType: "application/json", body: JSON.stringify(body) });
  });

  await loginThroughUi(page);
  await page.goto("/#inbox");
  const composer = page.getByRole("textbox", { name: "Resposta ao contato" });

  await page.locator("button.conv", { hasText: "Contato liberado fictício" }).click();
  await composer.fill("Resposta sintética liberada");
  await page.getByRole("button", { name: "Enviar mensagem" }).click();
  await expect(page.locator(".ds-toast")).toContainText("Resposta enviada pelo número oficial.");
  expect(sent).toEqual(["Resposta sintética liberada"]);

  await page.locator("button.conv", { hasText: "Contato em opt-out fictício" }).click();
  await composer.fill("Resposta sintética bloqueada");
  await page.getByRole("button", { name: "Enviar mensagem" }).click();
  await expect(page.locator(".ds-toast")).toContainText("pediu para não receber mensagens (opt-out)");
  await expect(composer).toHaveValue("Resposta sintética bloqueada");
  expect(sent).toEqual(["Resposta sintética liberada"]);
  // O 409 esperado aparece no console do navegador; nada além dele.
  expect(safety.consoleErrors.filter((text) => !text.includes("409"))).toEqual([]);
  expect(safety.pageErrors).toEqual([]);
  expect(safety.externalRequests).toEqual([]);
});
