import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchPublicAgentProfile,
  fetchLlmModels,
  saveCredential,
  savePublicAgentProfile,
  updateLlmModel,
} from "./agent-api";
import { ApiError } from "./dashboard-api";

let fetchMock: ReturnType<typeof vi.fn>;

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

describe("catálogo de modelos LLM", () => {
  it("usa o catálogo autoritativo devolvido pelo backend", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        padrao: "gpt-5.6-luna",
        precosAtualizadosEm: "2026-08-08",
        modelos: [
          {
            modelo: "gpt-5.6-luna",
            nome: "Luna — econômico",
            perfil: "alto volume",
            precoEntradaUsdMilhao: 0.2,
            precoSaidaUsdMilhao: 1.2,
            recomendado: true,
            fallback: [],
          },
        ],
      }),
    );

    const catalog = await fetchLlmModels("tok");

    expect(catalog.padrao).toBe("gpt-5.6-luna");
    expect(catalog.modelos.at(0)?.recomendado).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/models");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
  });
});

describe("persistência da escolha por tenant", () => {
  it("envia credencial e modelo juntos sem acrescentar outros campos", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        status: "active",
        provedor: "openai",
        modelo: "gpt-5.6-terra",
        validado: true,
      }),
    );

    await saveCredential("tok", {
      provedor: "openai",
      apiKey: "sk-tenant",
      modelo: "gpt-5.6-terra",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/credential");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      provedor: "openai",
      apiKey: "sk-tenant",
      modelo: "gpt-5.6-terra",
    });
  });

  it("troca somente o modelo quando a chave já está cifrada no servidor", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ modelo: "gpt-5.6-sol", validado: true }),
    );

    const result = await updateLlmModel("tok", "gpt-5.6-sol");

    expect(result).toEqual({ modelo: "gpt-5.6-sol", validado: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/model");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ modelo: "gpt-5.6-sol" });
    expect(init.body).not.toContain("apiKey");
  });

  it("preserva a mensagem de modelo sem acesso retornada pelo backend", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "A credencial não possui acesso ao modelo" }, 422),
    );

    const error = await updateLlmModel("tok", "gpt-5.6-sol").catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toContain("não possui acesso");
  });
});

describe("perfil público da igreja", () => {
  it("lê o envelope estruturado da própria sessão", async () => {
    const profile = {
      configured: false,
      informacoesPublicas: { enderecoIgreja: null, horariosCulto: null, celulas: [] },
    };
    fetchMock.mockResolvedValue(jsonResponse(profile));

    expect(await fetchPublicAgentProfile("tok")).toEqual(profile);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/public-profile");
    expect(init.method ?? "GET").toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("substitui só os fatos públicos em camelCase e preserva erro 409", async () => {
    const facts = {
      enderecoIgreja: "Rua Exemplo, 100",
      horariosCulto: "Domingo, 19h",
      celulas: [{ bairro: "Centro", nome: "Esperança", encontro: null }],
    };
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ configured: true, informacoesPublicas: facts }),
    );
    expect(await savePublicAgentProfile("tok", facts)).toEqual({
      configured: true,
      informacoesPublicas: facts,
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/public-profile");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual(facts);
    expect(init.body).not.toContain("comportamento");
    expect(init.body).not.toContain("ativo");

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Configuração ausente" }, 409));
    const error = await savePublicAgentProfile("tok", facts).catch((reason) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
  });
});
