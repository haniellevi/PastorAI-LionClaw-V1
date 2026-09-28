// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ confirmAgentIdentity: vi.fn(), expireSession: vi.fn() }));
vi.mock("@/lib/dashboard-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/dashboard-api")>("@/lib/dashboard-api");
  return { ...actual, confirmAgentIdentity: mocks.confirmAgentIdentity };
});

import { SessionExpiredError } from "@/lib/api";
import { ApiError } from "@/lib/dashboard-api";
import { AgentIdentityConfirmation } from "./AgentIdentityConfirmation";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const identity = { token: "sessao-a", appUserId: "usuario-a", churchId: "igreja-a" };

function render(props = identity) {
  act(() => root.render(h(AgentIdentityConfirmation, { ...props, expireSession: mocks.expireSession })));
}

function button(): HTMLButtonElement {
  const found = container.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!found) throw new Error("Botão de confirmação ausente");
  return found;
}

function input(): HTMLInputElement {
  const found = container.querySelector("input");
  if (!found) throw new Error("Campo do código ausente");
  return found;
}

function enter(value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input(), value);
  input().dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.location.hash = "#perfil";
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  window.location.hash = "";
});

it("aceita código colado sem validar formato no cliente e limpa após confirmação", async () => {
  mocks.confirmAgentIdentity.mockResolvedValue({ status: "confirmed" });
  render();
  expect(container.textContent).toContain("consulte meu vínculo");
  expect(container.textContent).toContain("repita a consulta no WhatsApp");
  expect(container.textContent).not.toContain("#perfil");
  expect(container.textContent).toContain("15 minutos");
  expect(input().maxLength).toBe(128);
  expect(button().disabled).toBe(true);
  act(() => enter("  codigo-opaco  "));
  await act(async () => button().click());

  expect(mocks.confirmAgentIdentity).toHaveBeenCalledWith(
    "sessao-a", "codigo-opaco", expect.any(AbortSignal),
  );
  expect(input().value).toBe("");
  expect(container.textContent).toContain("Conversa confirmada. Volte ao WhatsApp.");
  expect(container.querySelector('[role="status"]')?.nextElementSibling?.textContent).toContain("15 minutos");
  expect(window.location.hash).toBe("#perfil");
  expect(window.localStorage.length).toBe(0);
  expect(window.sessionStorage.length).toBe(0);
});

it("não envia código maior que o limite do campo", async () => {
  render();
  act(() => enter("x".repeat(129)));
  expect(button().disabled).toBe(true);
  await act(async () => button().click());
  expect(mocks.confirmAgentIdentity).not.toHaveBeenCalled();
});

it.each([410, 422])("rejeição %i não ecoa detalhes nem conserva código", async (status) => {
  mocks.confirmAgentIdentity.mockRejectedValue(new ApiError(status, "vínculo privado"));
  render();
  act(() => enter("codigo-rejeitado"));
  await act(async () => button().click());

  expect(input().value).toBe("");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Código inválido");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("repita a consulta sensível");
  expect(container.textContent).not.toContain("vínculo privado");
  expect(container.textContent).not.toContain("codigo-rejeitado");
});

it.each([404, 405, 501])("API ausente %i informa indisponibilidade sem expor resposta", async (status) => {
  mocks.confirmAgentIdentity.mockRejectedValue(new ApiError(status, "trace privado: codigo-opaco"));
  render();
  act(() => enter("codigo-opaco"));
  await act(async () => button().click());
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("indisponível nesta versão");
  expect(container.textContent).not.toContain("trace privado");
  expect(container.textContent).not.toContain("codigo-opaco");
  expect(input().value).toBe("");
});

it("401 encerra sessão e falha transitória não tenta novamente", async () => {
  mocks.confirmAgentIdentity.mockRejectedValueOnce(new SessionExpiredError());
  render();
  act(() => enter("codigo-um"));
  await act(async () => button().click());
  expect(mocks.expireSession).toHaveBeenCalledTimes(1);
  expect(input().value).toBe("");

  mocks.confirmAgentIdentity.mockRejectedValueOnce(new Error("rede"));
  act(() => enter("codigo-dois"));
  await act(async () => button().click());
  expect(mocks.confirmAgentIdentity).toHaveBeenCalledTimes(2);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível confirmar");
  expect(input().value).toBe("");
});

it("troca de conta aborta POST pendente e descarta sucesso antigo", async () => {
  let resolve!: (result: unknown) => void;
  mocks.confirmAgentIdentity.mockReturnValue(new Promise((done) => { resolve = done; }));
  render();
  act(() => enter("codigo-antigo"));
  await act(async () => { button().click(); await Promise.resolve(); });
  const oldSignal = mocks.confirmAgentIdentity.mock.calls[0]?.[2] as AbortSignal;
  expect(button().disabled).toBe(true);

  render({ token: "sessao-b", appUserId: "usuario-b", churchId: "igreja-b" });
  expect(oldSignal.aborted).toBe(true);
  expect(input().value).toBe("");
  await act(async () => resolve({ status: "confirmed" }));
  expect(container.textContent).not.toContain("Conversa confirmada.");
  expect(button().disabled).toBe(true);
});

it("rejeição antiga não afeta nova sessão nem exibe alerta", async () => {
  let reject!: (reason: unknown) => void;
  mocks.confirmAgentIdentity.mockReturnValue(new Promise((_done, fail) => { reject = fail; }));
  render();
  act(() => enter("codigo-antigo"));
  await act(async () => { button().click(); await Promise.resolve(); });
  render({ ...identity, appUserId: "usuario-b" });
  await act(async () => reject(new ApiError(403, "dado da sessão antiga")));
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(input().value).toBe("");
});

it("429 informa espera sem repetir envio ou divulgar código", async () => {
  mocks.confirmAgentIdentity.mockRejectedValue(new ApiError(429, "detalhe privado"));
  render();
  act(() => enter("codigo-opaco"));
  await act(async () => button().click());
  expect(mocks.confirmAgentIdentity).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Muitas tentativas");
  expect(container.textContent).not.toContain("detalhe privado");
  expect(input().value).toBe("");
});

it("duplo submit durante requisição pendente envia uma vez", async () => {
  let resolve!: (result: unknown) => void;
  mocks.confirmAgentIdentity.mockReturnValue(new Promise((done) => { resolve = done; }));
  render();
  act(() => enter("codigo-opaco"));
  await act(async () => { button().click(); button().click(); await Promise.resolve(); });
  expect(mocks.confirmAgentIdentity).toHaveBeenCalledTimes(1);
  expect(button().disabled).toBe(true);
  await act(async () => resolve({ status: "confirmed" }));
});
