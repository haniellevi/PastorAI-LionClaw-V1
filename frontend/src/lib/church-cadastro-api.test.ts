import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { fetchChurchCadastroCapability, getChurchCadastro, saveChurchCadastro } from "./church-cadastro-api";
import { SessionExpiredError } from "./api";

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

it("só reconhece capability version:1 e não usa cache", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ version: 1 }))
    .mockResolvedValueOnce(Response.json({ version: 2 }))
    .mockResolvedValueOnce(new Response(null, { status: 404 }));
  expect(await fetchChurchCadastroCapability("token-a")).toBe(true);
  expect(await fetchChurchCadastroCapability("token-a")).toBe(false);
  expect(await fetchChurchCadastroCapability("token-a")).toBe(false);
  expect(fetchMock).toHaveBeenCalledTimes(3);
  for (const [url, init] of fetchMock.mock.calls) {
    expect(url).toContain("/igreja/cadastro/capabilities");
    expect(init.cache).toBe("no-store");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-a");
  }
});

it("falha fechada em erro e preserva expiração de sessão", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(new Response(null, { status: 401 }));
  expect(await fetchChurchCadastroCapability("token-a")).toBe(false);
  await expect(fetchChurchCadastroCapability("token-a")).rejects.toBeInstanceOf(SessionExpiredError);
});

it("GET e PUT usam apenas o cadastro institucional da sessão", async () => {
  const data = { enderecoInstitucional: "Rua Exemplo, 100", horariosCulto: "Domingo, 19h" };
  fetchMock.mockResolvedValueOnce(Response.json(data)).mockResolvedValueOnce(Response.json(data));
  expect(await getChurchCadastro("token-a")).toEqual(data);
  expect(await saveChurchCadastro("token-a", data)).toEqual(data);
  const [getUrl, getInit] = fetchMock.mock.calls[0] as [string, RequestInit];
  const [putUrl, putInit] = fetchMock.mock.calls[1] as [string, RequestInit];
  expect(getUrl).toContain("/igreja/cadastro");
  expect(getInit.cache).toBe("no-store");
  expect(putUrl).toBe(getUrl);
  expect(putInit.method).toBe("PUT");
  expect(JSON.parse(putInit.body as string)).toEqual(data);
});
