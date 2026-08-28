import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdminAuthError,
  AdminRequestError,
  AdminSessionExpiredError,
  adminLogin,
  fetchAdminMe,
  fetchIgrejaConsentGovernance,
  initializeIgrejaConsentGovernance,
  updateIgrejaConsentGovernancePurpose,
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

describe("governança de consentimento draft-only", () => {
  const state = {
    enabled: true,
    initialized: false,
    schemaVersion: "d2b2b3a/v1",
    revision: 0,
    purposes: [],
  };

  it("lê o estado tenant-bound com o token do console", async () => {
    mockResponse(200, state);

    await expect(fetchIgrejaConsentGovernance("tok", "igreja-1")).resolves.toEqual(
      state,
    );

    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "http://localhost:8000/admin/igrejas/igreja-1/consent-governance",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("trata 404 somente na descoberta GET como capability ainda ausente", async () => {
    mockResponse(404, { detail: "Not Found" });

    await expect(
      fetchIgrejaConsentGovernance("tok", "igreja-1"),
    ).resolves.toEqual({
      enabled: false,
      initialized: false,
      schemaVersion: "d2b2b3a/governance-draft/v1",
      revision: 0,
      purposes: [],
    });
  });

  it("inicializa os rascunhos por POST sem enviar conteúdo implícito", async () => {
    mockResponse(200, { ...state, initialized: true, revision: 1 });

    await initializeIgrejaConsentGovernance("tok", "igreja-1");

    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "http://localhost:8000/admin/igrejas/igreja-1/consent-governance/initialize",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer tok" },
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("mantém 404 de mutation como erro", async () => {
    mockResponse(404, { detail: "Not Found" });

    await expect(
      initializeIgrejaConsentGovernance("tok", "igreja-1"),
    ).rejects.toMatchObject({ status: 404 });
  });

  it("salva somente revisão esperada e payload operacional estrito", async () => {
    mockResponse(200, { ...state, initialized: true, revision: 2 });
    const decisionPayload = {
      realProcessingAgents: "Equipe pastoral",
      operationsAndMinimumData: null,
      dataSensitivityAssessment: null,
      operationalNeed: "Responder pedidos recebidos",
      systemsAndRecipients: null,
      retentionAndDisposalInventory: null,
      operatorInstructions: null,
      openQuestions: null,
    };

    await updateIgrejaConsentGovernancePurpose(
      "tok",
      "igreja-1",
      "atendimento_solicitado",
      { expectedRevision: 4, decisionPayload },
    );

    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "http://localhost:8000/admin/igrejas/igreja-1/consent-governance/purposes/atendimento_solicitado",
      expect.objectContaining({
        method: "PUT",
        headers: {
          Authorization: "Bearer tok",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ expectedRevision: 4, decisionPayload }),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("aborta a descoberta pendurada no prazo sem confundir com sessão expirada", async () => {
    vi.useFakeTimers();
    const getSignal = mockPendingFetch();

    const assertion = expect(
      fetchIgrejaConsentGovernance("tok", "igreja-1"),
    ).rejects.toMatchObject({ kind: "network" });
    await vi.advanceTimersByTimeAsync(19_999);
    expect(getSignal()?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });

  it("distingue sessão expirada, acesso negado e conflito de revisão", async () => {
    mockResponse(401);
    await expect(fetchIgrejaConsentGovernance("tok", "igreja-1")).rejects.toBeInstanceOf(
      AdminSessionExpiredError,
    );

    mockResponse(403);
    await expect(initializeIgrejaConsentGovernance("tok", "igreja-1")).rejects.toMatchObject({
      kind: "forbidden",
    });

    mockResponse(409, { detail: "Revisão divergente." });
    await expect(
      updateIgrejaConsentGovernancePurpose(
        "tok",
        "igreja-1",
        "comunicados",
        {
          expectedRevision: 1,
          decisionPayload: {
            realProcessingAgents: null,
            operationsAndMinimumData: null,
            dataSensitivityAssessment: null,
            operationalNeed: null,
            systemsAndRecipients: null,
            retentionAndDisposalInventory: null,
            operatorInstructions: null,
            openQuestions: null,
          },
        },
      ),
    ).rejects.toEqual(expect.objectContaining<Partial<AdminRequestError>>({
      status: 409,
      message: "Revisão divergente.",
    }));
  });
});
