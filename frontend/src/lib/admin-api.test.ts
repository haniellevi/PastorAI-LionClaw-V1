import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdminAuthError,
  AdminSessionExpiredError,
  adminLogin,
  fetchAdminMe,
} from "./admin-api";

function mockResponse(status: number, body?: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

function mockPendingFetch(): () => AbortSignal | null {
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
  return () => observedSignal;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("adminLogin", () => {
  it("mantém 401 como recusa de acesso", async () => {
    mockResponse(401);

    await expect(adminLogin("admin@example.com", "senha")).rejects.toMatchObject({
      kind: "forbidden",
    });
  });

  it("trata 5xx como indisponibilidade, não como credencial inválida", async () => {
    mockResponse(503);

    await expect(adminLogin("admin@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
    });
  });

  it("rejeita resposta 200 sem token válido", async () => {
    mockResponse(200, { token: "" });

    await expect(adminLogin("admin@example.com", "senha")).rejects.toMatchObject({
      kind: "network",
    });
  });

  it("interrompe request pendurado no prazo", async () => {
    vi.useFakeTimers();
    const getSignal = mockPendingFetch();

    const assertion = expect(adminLogin("admin@example.com", "senha")).rejects.toBeInstanceOf(
      AdminAuthError,
    );
    await vi.advanceTimersByTimeAsync(19_999);
    expect(getSignal()?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });
});

describe("fetchAdminMe", () => {
  it("expira a sessão somente em 401", async () => {
    mockResponse(401);

    await expect(fetchAdminMe("token")).rejects.toBeInstanceOf(
      AdminSessionExpiredError,
    );
  });

  it.each([500, 503])("trata %s como indisponibilidade transitória", async (status) => {
    mockResponse(status);

    await expect(fetchAdminMe("token")).rejects.toMatchObject({ kind: "network" });
  });

  it("trata 403 como recusa terminal e preserva a mensagem estruturada", async () => {
    mockResponse(403, { detail: "Acesso administrativo revogado." });

    await expect(fetchAdminMe("token")).rejects.toMatchObject({
      kind: "forbidden",
      message: "Acesso administrativo revogado.",
    });
  });

  it("não trata outra recusa 4xx como indisponibilidade recuperável", async () => {
    mockResponse(422, { detail: "Sessão administrativa recusada." });

    await expect(fetchAdminMe("token")).rejects.toMatchObject({ kind: "forbidden" });
  });

  it("rejeita perfil 200 malformado sem expirar a sessão", async () => {
    mockResponse(200, { appUserId: "admin-1" });

    await expect(fetchAdminMe("token")).rejects.toMatchObject({ kind: "network" });
  });

  it("interrompe validação pendurada no prazo sem expirar a sessão", async () => {
    vi.useFakeTimers();
    const getSignal = mockPendingFetch();

    const assertion = expect(fetchAdminMe("token")).rejects.toMatchObject({
      kind: "network",
    });
    await vi.advanceTimersByTimeAsync(19_999);
    expect(getSignal()?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });
});
