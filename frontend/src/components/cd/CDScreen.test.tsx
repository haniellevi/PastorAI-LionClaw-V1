// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { CDScreen } from "./CDScreen";
const state = vi.hoisted(() => ({ request: vi.fn(), roles: ["admin"] }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ token: "synthetic", user: { roles: state.roles, churchId: "church", appUserId: "user" } }) }));
vi.mock("@/lib/cd-api", () => ({ cdRequest: (...args: unknown[]) => state.request(...args) }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root;
const turma = { id: "turma", nome: "Turma teste", encerrada: false };
const modulo = { id: "m", numero: 1, nome: "Módulo 1", nivel_id: null, aulas: Array.from({ length: 10 }, (_, i) => ({ id: `a${i}`, numero: i + 1, nome: `Aula ${i + 1}` })) };
const detail = { ...turma, versao: "1", modulo, calendario: [], responsaveis: [] };
const button = (text: string) => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes(text));
async function render() { await act(async () => { root.render(h(CDScreen)); }); }
beforeEach(() => {
  state.roles = ["admin"]; state.request.mockReset();
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path === "/curriculos" || path === "/opcoes" ? [] : detail));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
it("consulta dez aulas e oferece criação sem matrícula ou certificado", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.querySelectorAll('input[type="date"]')).toHaveLength(10);
  expect(button("Criar currículo")).toBeDefined(); expect(button("Criar turma")).toBeDefined();
  expect(container.textContent).not.toMatch(/Matricular|Certificar/);
  expect(state.request.mock.calls.every(c => c[2] === "GET")).toBe(true);
});
it("responsável tem somente consulta e não carrega catálogo ou equipe", async () => {
  state.roles = ["lider_consol"]; await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Criar turma")).toBeUndefined(); expect(button("Salvar calendário")).toBeUndefined();
  expect(button("Encerrar turma")).toBeUndefined();
  expect(Array.from(container.querySelectorAll("fieldset")).every(f => f.disabled)).toBe(true);
  expect(state.request.mock.calls.some(c => ["/curriculos", "/opcoes"].includes(c[1]))).toBe(false);
});
it("recusa operador antes de carregar dados", async () => {
  state.roles = ["operador"]; await render(); expect(container.querySelector('[role="alert"]')).not.toBeNull(); expect(state.request).not.toHaveBeenCalled();
});
it("encerramento requer confirmação", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); button("Encerrar turma")?.click(); });
  await act(async () => { button("Encerrar turma")!.click(); });
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
  await act(async () => { button("Confirmar encerramento")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/encerrar", "POST", undefined, expect.any(AbortSignal));
});
it("turma encerrada mantém consulta e permite reabertura só à coordenação", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path === "/curriculos" ? [] : { ...detail, encerrada: true }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Reabrir turma")).toBeDefined();
  expect(container.querySelector<HTMLFieldSetElement>(".uv-detail fieldset")?.disabled).toBe(true);
});
it("erro de transporte é recuperável", async () => {
  state.request.mockRejectedValueOnce(new Error("Falha de conexão")); await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Falha de conexão"); expect(button("Atualizar")?.disabled).toBe(false);
});
