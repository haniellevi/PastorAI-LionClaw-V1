import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AssistantError, SessionExpiredError, sendAssistantMessage } from "./api";

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

it("envia só tenantId e texto, com o token da sessão", async () => {
  fetchMock.mockResolvedValue(reply(200, { resposta: "ok", telasSugeridas: ["dashboard"] }));
  const out = await sendAssistantMessage("tok", "igreja-1", "oi");
  expect(out).toEqual({ resposta: "ok", telasSugeridas: ["dashboard"] });
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(String(url)).toMatch(/\/assistant\/message$/);
  expect(init.headers.Authorization).toBe("Bearer tok");
  expect(JSON.parse(init.body)).toEqual({ tenantId: "igreja-1", texto: "oi" });
});

it("401 vira sessão expirada; 403 vira recusa sem detalhe do servidor", async () => {
  fetchMock.mockResolvedValueOnce(reply(401, { detail: "x" }));
  await expect(sendAssistantMessage("t", "i", "oi")).rejects.toBeInstanceOf(SessionExpiredError);
  fetchMock.mockResolvedValueOnce(reply(403, { detail: "tenant não corresponde" }));
  const error = await sendAssistantMessage("t", "i", "oi").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(AssistantError);
  expect((error as AssistantError).kind).toBe("forbidden");
  expect((error as AssistantError).message).not.toContain("tenant");
});

it("5xx, rede e corpo inválido viram indisponível", async () => {
  fetchMock.mockResolvedValueOnce(reply(503, { detail: "x" }));
  await expect(sendAssistantMessage("t", "i", "oi")).rejects.toMatchObject({ kind: "unavailable" });
  fetchMock.mockRejectedValueOnce(new TypeError("fail"));
  await expect(sendAssistantMessage("t", "i", "oi")).rejects.toMatchObject({ kind: "unavailable" });
  fetchMock.mockResolvedValueOnce(reply(200, { resposta: 1 }));
  await expect(sendAssistantMessage("t", "i", "oi")).rejects.toMatchObject({ kind: "unavailable" });
});

it("422 vira erro de validação com a mensagem do servidor", async () => {
  fetchMock.mockResolvedValue(reply(422, { detail: "texto obrigatório" }));
  await expect(sendAssistantMessage("t", "i", "oi")).rejects.toMatchObject({
    kind: "invalid",
    message: "texto obrigatório",
  });
});
