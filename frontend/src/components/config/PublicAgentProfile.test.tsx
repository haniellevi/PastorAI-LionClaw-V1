// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchPublicAgentProfile: vi.fn(),
  savePublicAgentProfile: vi.fn(),
  expireSession: vi.fn(),
}));

vi.mock("@/lib/agent-api", () => ({
  fetchPublicAgentProfile: mocks.fetchPublicAgentProfile,
  savePublicAgentProfile: mocks.savePublicAgentProfile,
}));

import { PublicAgentProfile } from "./PublicAgentProfile";
import { ApiError } from "@/lib/dashboard-api";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;

function button(name: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name,
  );
  if (!found) throw new Error(`Botão ausente: ${name}`);
  return found;
}

function change(id: string, value: string): void {
  const element = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(`#${id}`);
  if (!element) throw new Error(`Campo ausente: ${id}`);
  const setter = Object.getOwnPropertyDescriptor(
    element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

const empty = { enderecoIgreja: null, horariosCulto: null, celulas: [] };

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.fetchPublicAgentProfile.mockResolvedValue({ configured: true, informacoesPublicas: empty });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("mantém salvar indisponível até o GET e quando a plataforma não configurou o agente", async () => {
  let resolve!: (value: unknown) => void;
  mocks.fetchPublicAgentProfile.mockReturnValue(new Promise((done) => { resolve = done; }));
  act(() => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  expect(button("Salvar informações públicas").disabled).toBe(true);
  await act(async () => {
    resolve({ configured: false, informacoesPublicas: empty });
  });
  expect(container.textContent).toContain("Aguarde a configuração do agente pela plataforma");
  expect(button("Salvar informações públicas").disabled).toBe(true);
  expect(mocks.savePublicAgentProfile).not.toHaveBeenCalled();
});

it("salva apenas fatos públicos, limita cinco células e mostra valores ao reabrir", async () => {
  mocks.savePublicAgentProfile.mockImplementation(async (_token, facts) => ({
    configured: true,
    informacoesPublicas: facts,
  }));
  await act(async () => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  act(() => {
    change("publicEndereco", " Rua Exemplo, 100 ");
    change("publicHorarios", " Domingo, 19h ");
    for (let index = 0; index < 5; index += 1) button("Adicionar célula").click();
  });
  expect(button("Adicionar célula").disabled).toBe(true);
  act(() => {
    change("publicBairro0", "Centro");
    change("publicNome0", "Esperança");
    for (let index = 1; index < 5; index += 1) button(`Remover célula ${index + 1}`).click();
  });
  await act(async () => button("Salvar informações públicas").click());
  expect(mocks.savePublicAgentProfile).toHaveBeenCalledWith("tenant", {
    enderecoIgreja: "Rua Exemplo, 100",
    horariosCulto: "Domingo, 19h",
    celulas: [{ bairro: "Centro", nome: "Esperança", encontro: null }],
  });
  expect(container.textContent).toContain("Informações públicas salvas.");

  act(() => root.unmount());
  root = createRoot(container);
  const saved = mocks.savePublicAgentProfile.mock.results.at(0)?.value;
  if (!saved) throw new Error("Resposta salva ausente");
  mocks.fetchPublicAgentProfile.mockResolvedValueOnce(saved);
  await act(async () => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  expect(container.querySelector<HTMLInputElement>("#publicEndereco")?.value).toBe("Rua Exemplo, 100");
  expect(container.querySelector<HTMLInputElement>("#publicNome0")?.value).toBe("Esperança");
});

it("preserva edição após falha e recusa célula incompleta", async () => {
  mocks.savePublicAgentProfile.mockRejectedValue(new Error("falha sintética"));
  await act(async () => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  act(() => button("Adicionar célula").click());
  await act(async () => button("Salvar informações públicas").click());
  expect(container.getAttribute("role")).toBeNull();
  expect(container.textContent).toContain("Preencha bairro e nome");
  expect(mocks.savePublicAgentProfile).not.toHaveBeenCalled();
  act(() => {
    change("publicBairro0", "Centro");
    change("publicNome0", "Esperança");
  });
  await act(async () => button("Salvar informações públicas").click());
  expect(container.textContent).toContain("Não foi possível salvar as informações públicas");
  expect(container.querySelector<HTMLInputElement>("#publicNome0")?.value).toBe("Esperança");
});

it("isola falha de GET e permite tentar novamente", async () => {
  mocks.fetchPublicAgentProfile.mockRejectedValueOnce(new Error("offline"));
  await act(async () => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível carregar");
  expect(button("Salvar informações públicas").disabled).toBe(true);
  await act(async () => button("Tentar novamente").click());
  expect(mocks.fetchPublicAgentProfile).toHaveBeenCalledTimes(2);
  expect(button("Salvar informações públicas").disabled).toBe(false);
});

it("409 bloqueia edição sem criar configuração nem ativar o agente", async () => {
  mocks.savePublicAgentProfile.mockRejectedValue(new ApiError(409, "Configuração ausente"));
  await act(async () => root.render(h(PublicAgentProfile, { token: "tenant", expireSession: mocks.expireSession })));
  await act(async () => button("Salvar informações públicas").click());
  expect(container.textContent).toContain("Aguarde a configuração do agente pela plataforma");
  expect(button("Salvar informações públicas").disabled).toBe(true);
});

it("troca de token seguida de GET rejeitado bloqueia dados antigos e oferece retry", async () => {
  mocks.fetchPublicAgentProfile.mockResolvedValueOnce({
    configured: true,
    informacoesPublicas: { ...empty, enderecoIgreja: "Endereço da igreja A" },
  });
  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-a", expireSession: mocks.expireSession })));
  expect(button("Salvar informações públicas").disabled).toBe(false);
  mocks.fetchPublicAgentProfile.mockRejectedValueOnce(new Error("offline"));

  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-b", expireSession: mocks.expireSession })));

  expect(mocks.fetchPublicAgentProfile).toHaveBeenLastCalledWith("igreja-b");
  expect(button("Salvar informações públicas").disabled).toBe(true);
  expect(button("Tentar novamente")).toBeTruthy();
  expect(container.querySelector<HTMLInputElement>("#publicEndereco")?.value).toBe("");
  expect(mocks.savePublicAgentProfile).not.toHaveBeenCalled();
});

it("PUT antigo não sobrescreve nem habilita perfil após troca de token", async () => {
  let resolvePut!: (value: unknown) => void;
  mocks.savePublicAgentProfile.mockReturnValue(new Promise((resolve) => { resolvePut = resolve; }));
  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-a", expireSession: mocks.expireSession })));
  act(() => change("publicEndereco", "Endereço da igreja A"));
  await act(async () => { button("Salvar informações públicas").click(); await Promise.resolve(); });
  expect(mocks.savePublicAgentProfile).toHaveBeenCalledWith("igreja-a", expect.anything());

  mocks.fetchPublicAgentProfile.mockResolvedValueOnce({ configured: false, informacoesPublicas: empty });
  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-b", expireSession: mocks.expireSession })));
  await act(async () => resolvePut({
    configured: true,
    informacoesPublicas: { ...empty, enderecoIgreja: "Endereço da igreja A" },
  }));

  expect(button("Salvar informações públicas").disabled).toBe(true);
  expect(container.querySelector<HTMLInputElement>("#publicEndereco")?.value).toBe("");
  expect(container.textContent).not.toContain("Informações públicas salvas.");
  expect(mocks.savePublicAgentProfile).toHaveBeenCalledTimes(1);
});

it("rejeição tardia do PUT anterior não mostra erro no novo token", async () => {
  let rejectPut!: (reason: unknown) => void;
  mocks.savePublicAgentProfile.mockReturnValue(new Promise((_resolve, reject) => { rejectPut = reject; }));
  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-a", expireSession: mocks.expireSession })));
  await act(async () => { button("Salvar informações públicas").click(); await Promise.resolve(); });
  mocks.fetchPublicAgentProfile.mockResolvedValueOnce({
    configured: true,
    informacoesPublicas: { ...empty, enderecoIgreja: "Endereço da igreja B" },
  });
  await act(async () => root.render(h(PublicAgentProfile, { token: "igreja-b", expireSession: mocks.expireSession })));

  await act(async () => rejectPut(new ApiError(422, "Erro da igreja A")));

  expect(container.querySelector<HTMLInputElement>("#publicEndereco")?.value).toBe("Endereço da igreja B");
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(button("Salvar informações públicas").disabled).toBe(false);
});
