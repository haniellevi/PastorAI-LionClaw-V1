// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(), capability: vi.fn(), get: vi.fn(), save: vi.fn(), expireSession: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: mocks.useAuth }));
vi.mock("@/lib/church-cadastro-api", () => ({
  fetchChurchCadastroCapability: mocks.capability,
  getChurchCadastro: mocks.get,
  saveChurchCadastro: mocks.save,
}));

import { CadastroIgrejaScreen } from "./CadastroIgrejaScreen";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const empty = { enderecoInstitucional: null, horariosCulto: null };

function render(token = "sessao-a", churchId = "igreja-a") {
  mocks.useAuth.mockReturnValue({
    token, user: { appUserId: `user-${churchId}`, churchId, roles: ["admin"] },
    expireSession: mocks.expireSession,
  });
  act(() => root.render(h(CadastroIgrejaScreen)));
}

function change(id: string, value: string) {
  const input = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(`#${id}`);
  if (!input) throw new Error(`Campo ausente: ${id}`);
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.capability.mockResolvedValue(true);
  mocks.get.mockResolvedValue(empty);
  mocks.save.mockImplementation(async (_token, data) => data);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

it("backend antigo ou sem suporte esconde campos e não lê nem salva cadastro", async () => {
  mocks.capability.mockResolvedValue(false);
  await act(async () => render());
  expect(container.textContent).toContain("Cadastro da igreja");
  expect(container.querySelector("#cadastroEndereco")).toBeNull();
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.save).not.toHaveBeenCalled();
});

it("papel sem admin não consulta nem edita o cadastro", async () => {
  mocks.useAuth.mockReturnValue({
    token: "sessao-a", user: { appUserId: "user-a", churchId: "igreja-a", roles: ["pastor"] },
    expireSession: mocks.expireSession,
  });
  await act(async () => root.render(h(CadastroIgrejaScreen)));
  expect(container.textContent).toContain("Somente administradores");
  expect(mocks.capability).not.toHaveBeenCalled();
  expect(container.querySelector("#cadastroEndereco")).toBeNull();
});

it("admin salva e reabre somente endereço institucional e horários", async () => {
  await act(async () => render());
  act(() => { change("cadastroEndereco", " Rua Exemplo, 100 "); change("cadastroHorarios", " Domingo, 19h "); });
  await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click());
  expect(mocks.save).toHaveBeenCalledWith("sessao-a", {
    enderecoInstitucional: "Rua Exemplo, 100", horariosCulto: "Domingo, 19h",
  }, expect.any(AbortSignal));
  expect(container.textContent).toContain("Cadastro salvo.");
  act(() => root.unmount());
  root = createRoot(container);
  mocks.get.mockResolvedValueOnce({ enderecoInstitucional: "Rua Exemplo, 100", horariosCulto: "Domingo, 19h" });
  await act(async () => render());
  expect(container.querySelector<HTMLInputElement>("#cadastroEndereco")?.value).toBe("Rua Exemplo, 100");
});

it("troca de tenant mascara valores antigos e ignora GET tardio sem suporte", async () => {
  await act(async () => render());
  act(() => change("cadastroEndereco", "Endereco A"));
  mocks.capability.mockResolvedValueOnce(false);
  render("sessao-b", "igreja-b");
  expect(container.textContent).not.toContain("Endereco A");
  await act(async () => Promise.resolve());
  expect(container.querySelector("#cadastroEndereco")).toBeNull();
  expect(mocks.save).not.toHaveBeenCalled();
});

it("GET antigo resolvido após troca não expõe dados na nova sessão", async () => {
  let resolveA!: (value: unknown) => void;
  mocks.get.mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }));
  await act(async () => render());
  mocks.capability.mockResolvedValueOnce(false);
  await act(async () => render("sessao-a", "igreja-b"));
  await act(async () => resolveA({ enderecoInstitucional: "Endereco A", horariosCulto: null }));
  expect(container.textContent).not.toContain("Endereco A");
  expect(container.querySelector("#cadastroEndereco")).toBeNull();
});

it("PUT antigo concluído após troca de sessão não sobrescreve B", async () => {
  let resolveA!: (value: unknown) => void;
  mocks.save.mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }));
  await act(async () => render());
  act(() => change("cadastroEndereco", "Endereco A"));
  await act(async () => { container.querySelector<HTMLButtonElement>('button[type="submit"]')?.click(); await Promise.resolve(); });
  mocks.get.mockResolvedValueOnce({ enderecoInstitucional: "Endereco B", horariosCulto: null });
  await act(async () => render("sessao-b", "igreja-b"));
  await act(async () => resolveA({ enderecoInstitucional: "Endereco A", horariosCulto: null }));
  expect(container.querySelector<HTMLInputElement>("#cadastroEndereco")?.value).toBe("Endereco B");
  expect(container.textContent).not.toContain("Cadastro salvo.");
});
