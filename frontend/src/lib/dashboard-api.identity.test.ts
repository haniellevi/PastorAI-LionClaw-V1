import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SessionExpiredError } from "./api";
import { confirmAgentIdentity } from "./dashboard-api";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

it("envia somente o correlacionador no corpo autenticado, sem cache ou URL", async () => {
  fetchMock.mockResolvedValue(Response.json({ status: "confirmed" }));
  const controller = new AbortController();

  expect(await confirmAgentIdentity("sessao", "codigo-opaco", controller.signal)).toEqual({
    status: "confirmed",
  });
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("http://localhost:8000/agent/identity-confirmations");
  expect(init.method).toBe("POST");
  expect(init.cache).toBe("no-store");
  expect(init.signal).toBe(controller.signal);
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer sessao");
  expect(JSON.parse(init.body as string)).toEqual({ challenge: "codigo-opaco" });
});

it.each([400, 403, 409, 410, 422])("não ecoa detalhe de rejeição %i", async (status) => {
  fetchMock.mockResolvedValue(Response.json({ detail: "segredo e vínculo privado" }, { status }));
  const error = await confirmAgentIdentity("sessao", "codigo-opaco").catch((reason) => reason);
  expect(error.status).toBe(status);
  expect(error.message).toContain("Código inválido");
  expect(error.message).not.toContain("segredo");
  expect(error.message).not.toContain("vínculo");
});

it("mantém 401 como expiração e rejeita sucesso fora do contrato", async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
  await expect(confirmAgentIdentity("sessao", "codigo-opaco")).rejects.toBeInstanceOf(
    SessionExpiredError,
  );
  fetchMock.mockResolvedValueOnce(Response.json({ status: "pending" }));
  await expect(confirmAgentIdentity("sessao", "codigo-opaco")).rejects.toThrow(
    "Não foi possível confirmar a conversa.",
  );
});

it.each([404, 405, 501])("API ausente %i responde com mensagem compatível sem ecoar backend", async (status) => {
  fetchMock.mockResolvedValue(Response.json({ detail: "trace privado" }, { status }));
  const error = await confirmAgentIdentity("sessao", "codigo-opaco").catch((reason) => reason);
  expect(error.status).toBe(status);
  expect(error.message).toContain("indisponível nesta versão");
  expect(error.message).not.toContain("trace privado");
});
