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
