/**
 * Contrato do cliente do Google Agenda, exercitado pelo caminho REAL.
 *
 * Nada de mock do `authedFetch`: o dublê é o `fetch` global, então estes testes
 * atravessam `authedFetch` → `readDetail` → guardas de `calendar-api.ts`. É a
 * diferença entre provar o contrato e provar o próprio mock.
 *
 * O que travam:
 *  - `/connect` fail-closed: sem `flowSecret` OU sem `expiresAt` utilizável não
 *    existe fluxo concluível, então a função rejeita em vez de deixar o painel
 *    mandar o usuário consentir à toa;
 *  - `finishConnection` com segredo vazio nem chega a fazer requisição;
 *  - o 409 estruturado de conta divergente vira erro TIPADO, com as duas contas
 *    preservadas — `readDetail` reduziria tudo a string e perderia isso.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  GoogleAccountMismatchError,
  fetchConnectUrl,
  finishConnection,
} from "./calendar-api";

const EMAIL = "agenda@igreja12.com.br";

let fetchMock: ReturnType<typeof vi.fn>;

/** Resposta JSON crua — é o que `authedFetch` devolve ao chamador. */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchConnectUrl — fail-closed", () => {
  it("sem flowSecret rejeita com ApiError 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        authUrl: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        expiresAt: new Date(Date.now() + 600_000).toISOString(),
      }),
    );

    const err = await fetchConnectUrl("tok", EMAIL).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });

  it("sem expiresAt rejeita com ApiError 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        authUrl: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        flowSecret: "segredo",
      }),
    );

    const err = await fetchConnectUrl("tok", EMAIL).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });

  it("expiresAt inválido rejeita com ApiError 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        authUrl: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        flowSecret: "segredo",
        expiresAt: "amanhã de manhã",
      }),
    );

    const err = await fetchConnectUrl("tok", EMAIL).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });

  it("resposta completa devolve o prazo do SERVIDOR em epoch ms", async () => {
    const iso = "2026-07-31T23:45:00+00:00";
    fetchMock.mockResolvedValue(
      jsonResponse({
        authUrl: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        flowSecret: "segredo",
        expiresAt: iso,
      }),
    );

    const start = await fetchConnectUrl("tok", EMAIL);

    expect(start.flowSecret).toBe("segredo");
    expect(start.expiresAt).toBe(Date.parse(iso));
    // O prazo é o do servidor, não um TTL recalculado no cliente.
    expect(Number.isFinite(start.expiresAt)).toBe(true);
  });

  it("envia POST com a conta declarada no CORPO, nunca na URL", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        authUrl: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        flowSecret: "segredo",
        expiresAt: new Date(Date.now() + 600_000).toISOString(),
      }),
    );

    await fetchConnectUrl("tok", EMAIL);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ expectedGoogleEmail: EMAIL });
    expect(url).not.toContain(EMAIL); // nada de e-mail em query string
  });
});

describe("finishConnection — segredo obrigatório", () => {
  it("segredo vazio rejeita com ApiError 409 e não toca no fetch", async () => {
    const err = await finishConnection("tok", "").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("com segredo, o corpo enviado carrega exatamente aquele segredo", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        status: "conectado",
        connected: true,
        calendarId: "cal@x",
        googleAccountEmail: EMAIL,
      }),
    );

    const r = await finishConnection("tok", "segredo");

    expect(r).toEqual({
      status: "conectado",
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: EMAIL,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ flowSecret: "segredo" });
  });
});

describe("finishConnection — conta divergente", () => {
  it("409 estruturado vira erro tipado com as DUAS contas", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: "conta_divergente",
            expected: EMAIL,
            verified: "outra@gmail.com",
          },
        },
        409,
      ),
    );

    const err = await finishConnection("tok", "segredo").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(GoogleAccountMismatchError);
    expect((err as GoogleAccountMismatchError).expected).toBe(EMAIL);
    expect((err as GoogleAccountMismatchError).verified).toBe("outra@gmail.com");
  });

  it("409 com detail string segue sendo ApiError, com a mensagem preservada", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Esse endereço agora pertence a outra conta." }, 409),
    );

    const err = await finishConnection("tok", "segredo").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(GoogleAccountMismatchError);
    expect((err as ApiError).message).toContain("outra conta");
  });
});
