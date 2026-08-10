import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AuthUnavailableError,
  fetchMe,
  login,
  SessionAccessDeniedError,
  SessionExpiredError,
} from "./api";

function mockResponse(status: number, body?: unknown, headers?: HeadersInit): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      }),
    ),
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("login", () => {
  it("devolve token e perfil completos para hidratar a sessão sem /auth/me", async () => {
    const result = {
      token: "token_xyz",
      appUserId: "user-1",
      churchId: "church-1",
      email: "pessoa@example.com",
      nome: "Pessoa",
      chatNome: null,
      roles: ["pastor"],
      isOwner: false,
      igrejaNome: "Igreja",
      igrejaLogoUrl: null,
    };
    mockResponse(200, result);

    await expect(login("pessoa@example.com", "senha")).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("usa /auth/me como fallback para resposta legada antes de devolver o token", async () => {
    const me = {
      appUserId: "user-1",
      churchId: "church-1",
      email: "pessoa@example.com",
      nome: "Pessoa",
      chatNome: null,
      roles: ["pastor"],
      isOwner: false,
      igrejaNome: "Igreja",
      igrejaLogoUrl: null,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ token: "legacy-token", churchId: "church-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(me), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(login("pessoa@example.com", "senha")).resolves.toEqual({
      token: "legacy-token",
      ...me,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/auth/me");
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toEqual({
      Authorization: "Bearer legacy-token",
    });
  });

  it("não aceita resposta 200 sem token e perfil válidos", async () => {
    mockResponse(200, { churchId: "church-1", roles: [] });

    await expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("não conclui login legado quando /auth/me está indisponível", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ token: "legacy-token", churchId: "church-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(login("pessoa@example.com", "senha")).rejects.toBeInstanceOf(
      AuthUnavailableError,
    );
  });

  it.each([401, 422])(
    "mantém a resposta %s genérica para não enumerar contas",
    async (status) => {
      mockResponse(status, { detail: "detalhe que não deve chegar à interface" });

      await expect(login("pessoa@example.com", "senha-inválida")).rejects.toMatchObject({
        kind: "invalid",
        message: "Não foi possível autenticar. Verifique suas credenciais e tente novamente.",
      });
    },
  );

  it("preserva o bloqueio estruturado retornado em 403", async () => {
    mockResponse(403, {
      detail: {
        error: "billing_blocked",
        message: "Acesso bloqueado por pendência de assinatura.",
      },
    });

    await expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "billing_blocked",
      message: "Acesso bloqueado por pendência de assinatura.",
    });
  });

  it("orienta aguardar no 429 sem rotular como credencial inválida", async () => {
    mockResponse(429, undefined, { "Retry-After": "30" });

    await expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "rate_limited",
      message: "Muitas tentativas de acesso. Aguarde 30 segundos e tente novamente.",
    });
  });

  it("trata erro 500 como indisponibilidade temporária", async () => {
    mockResponse(500, { detail: "internal error" });

    await expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
      message:
        "O serviço de autenticação está temporariamente indisponível. Tente novamente em instantes.",
    });
  });

  it("trata falha de rede como indisponibilidade temporária", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    await expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
      message:
        "O serviço de autenticação está temporariamente indisponível. Tente novamente em instantes.",
    });
  });

  it("interrompe login pendurado no prazo de autenticação", async () => {
    vi.useFakeTimers();
    let observedSignal: AbortSignal | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        observedSignal = init?.signal ?? null;
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }),
    );

    const assertion = expect(login("pessoa@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
    });
    await vi.advanceTimersByTimeAsync(19_999);
    expect((observedSignal as AbortSignal | null)?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });
});

describe("fetchMe", () => {
  it("expira a sessão somente quando a API confirma 401", async () => {
    mockResponse(401);

    await expect(fetchMe("token")).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("encerra a sessão em 403 preservando a mensagem estruturada", async () => {
    mockResponse(403, {
      detail: { error: "access_denied", message: "Usuário sem acesso à igreja." },
    });

    const request = fetchMe("token");
    await expect(request).rejects.toMatchObject({
      name: "SessionAccessDeniedError",
      message: "Usuário sem acesso à igreja.",
    });
    await expect(request).rejects.toBeInstanceOf(SessionAccessDeniedError);
  });

  it("não trata outra recusa 4xx como indisponibilidade recuperável", async () => {
    mockResponse(422, { detail: "Sessão sem vínculo válido." });

    await expect(fetchMe("token")).rejects.toBeInstanceOf(SessionAccessDeniedError);
  });

  it("preserva a sessão quando /auth/me retorna 500", async () => {
    mockResponse(500);

    await expect(fetchMe("token")).rejects.toBeInstanceOf(AuthUnavailableError);
  });

  it("preserva a sessão quando /auth/me falha por rede", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    await expect(fetchMe("token")).rejects.toBeInstanceOf(AuthUnavailableError);
  });

  it("preserva a sessão quando /auth/me atinge o prazo", async () => {
    vi.useFakeTimers();
    let observedSignal: AbortSignal | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        observedSignal = init?.signal ?? null;
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }),
    );

    const assertion = expect(fetchMe("token")).rejects.toBeInstanceOf(
      AuthUnavailableError,
    );
    await vi.advanceTimersByTimeAsync(19_999);
    expect((observedSignal as AbortSignal | null)?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });

  it("rejeita perfil /auth/me malformado sem expirar a sessão", async () => {
    mockResponse(200, { churchId: "church-1", roles: ["pastor"] });

    await expect(fetchMe("token")).rejects.toBeInstanceOf(AuthUnavailableError);
  });
});
