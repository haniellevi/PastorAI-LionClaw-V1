// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createConfigRequest: vi.fn(),
  createCron: vi.fn(),
  expireSession: vi.fn(),
  fetchAgentConfig: vi.fn(),
  fetchConfigRequests: vi.fn(),
  fetchCredentialStatus: vi.fn(),
  fetchCrons: vi.fn(),
  fetchLlmModels: vi.fn(),
  fetchPublicAgentProfile: vi.fn(),
  saveCredential: vi.fn(),
  updateCron: vi.fn(),
  updateLlmModel: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tenant-token", expireSession: mocks.expireSession }),
}));

vi.mock("@/lib/agent-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/agent-api")>(
    "@/lib/agent-api",
  );
  return {
    ...actual,
    createConfigRequest: mocks.createConfigRequest,
    createCron: mocks.createCron,
    fetchAgentConfig: mocks.fetchAgentConfig,
    fetchConfigRequests: mocks.fetchConfigRequests,
    fetchCredentialStatus: mocks.fetchCredentialStatus,
    fetchCrons: mocks.fetchCrons,
    fetchLlmModels: mocks.fetchLlmModels,
    fetchPublicAgentProfile: mocks.fetchPublicAgentProfile,
    saveCredential: mocks.saveCredential,
    updateCron: mocks.updateCron,
    updateLlmModel: mocks.updateLlmModel,
  };
});

import { AgenteScreen } from "./AgenteScreen";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function findButton(label: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  if (!button) throw new Error(`Botão não encontrado: ${label}`);
  return button;
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.fetchCredentialStatus.mockResolvedValue({
    status: "active",
    provedor: "openai",
    modelo: "gpt-5.6-luna",
  });
  mocks.fetchLlmModels.mockResolvedValue({
    padrao: "gpt-5.6-luna",
    precosAtualizadosEm: "2026-08-25",
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
  });
  mocks.fetchAgentConfig.mockResolvedValue({ configured: false, ativo: false });
  mocks.fetchCrons.mockResolvedValue([]);
  mocks.fetchConfigRequests.mockResolvedValue([]);
  mocks.fetchPublicAgentProfile.mockResolvedValue({
    configured: false,
    informacoesPublicas: { enderecoIgreja: null, horariosCulto: null, celulas: [] },
  });
  mocks.updateLlmModel.mockResolvedValue({
    modelo: "gpt-5.6-luna",
    validado: true,
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("AgenteScreen: revalidação da BYO", () => {
  it.each(["fetchAgentConfig"] as const)(
    "não afirma que o assistente está desativado quando %s falha",
    async (failedLoad) => {
      mocks[failedLoad].mockRejectedValue(new Error("Falha sintética de leitura"));
      act(() => root.render(h(AgenteScreen)));
      await flush();

      expect(container.querySelector('[role="alert"]')?.textContent).toContain(
        "Não foi possível carregar",
      );
      expect(container.textContent).toContain("Estado do assistente indisponível");
      expect(container.textContent).not.toContain("Assistente desativado");
      expect(container.textContent).not.toContain("Assistente ativo");
      expect(container.querySelector(".seg-toggle-row")?.textContent).not.toMatch(/Desativado|Ativo/);
      expect(container.textContent).not.toContain("Ainda não configurado pela plataforma");
      act(() => findButton("Agendamentos").click());
      const cronName = container.querySelector<HTMLInputElement>("#cronName")!;
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(cronName, "Agendamento sintético");
        cronName.dispatchEvent(new Event("input", { bubbles: true }));
      });
      expect(findButton("Criar agendamento").disabled).toBe(true);
      expect(container.querySelector<HTMLInputElement>('.seg-toggle-row input[type="checkbox"]')?.disabled).toBe(true);
      await act(async () => {
        container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
      expect(mocks.createCron).not.toHaveBeenCalled();
      expect(mocks.updateCron).not.toHaveBeenCalled();
      expect(mocks.updateLlmModel).not.toHaveBeenCalled();
      expect(mocks.saveCredential).not.toHaveBeenCalled();
    },
  );

  it.each([true, false])("mostra somente o estado confirmado, ativo=%s", async (ativo) => {
    mocks.fetchAgentConfig.mockResolvedValue({ configured: true, ativo, nome: "Laboratório", comportamento: "Sintético" });
    act(() => root.render(h(AgenteScreen)));
    await flush();

    expect(container.textContent).toContain(ativo ? "Assistente ativo" : "Assistente desativado");
    expect(container.textContent).not.toContain("Estado do assistente indisponível");
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("catalogo de modelos lento/falho não esconde o estado confirmado do agente", async () => {
    mocks.fetchLlmModels.mockRejectedValue(new Error("Catálogo indisponível"));
    act(() => root.render(h(AgenteScreen)));
    await flush();
    expect(mocks.fetchLlmModels).not.toHaveBeenCalled();
    expect(mocks.fetchCrons).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Assistente desativado");
    act(() => findButton("Credencial LLM").click());
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível carregar esta seção");
    expect(container.textContent).toContain("Assistente desativado");
    expect(mocks.saveCredential).not.toHaveBeenCalled();
  });

  it("revalida a credencial ativa no mesmo modelo sem pedir ou reenviar a chave", async () => {
    act(() => root.render(h(AgenteScreen)));
    await flush();

    act(() => findButton("Credencial LLM").click());

    const keyInput = container.querySelector<HTMLInputElement>("#agKey")!;
    expect(keyInput.type).toBe("password");
    expect(keyInput.value).toBe("");

    const revalidate = findButton("Revalidar credencial");
    expect(revalidate.disabled).toBe(false);
    await act(async () => {
      revalidate.click();
      await Promise.resolve();
    });
    await flush();

    expect(mocks.updateLlmModel).toHaveBeenCalledWith(
      "tenant-token",
      "gpt-5.6-luna",
    );
    expect(mocks.saveCredential).not.toHaveBeenCalled();
    expect(keyInput.value).toBe("");
    expect(container.textContent).toContain("Credencial e modelo revalidados.");
  });
});
