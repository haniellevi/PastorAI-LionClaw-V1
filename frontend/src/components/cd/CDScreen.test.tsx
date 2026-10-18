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
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path === "/curriculos" || path === "/opcoes" || path.endsWith("/matriculas") ? [] : path.split("?")[0].endsWith("/elegiveis") ? [{ id: "p", nome: "Pessoa elegível" }] : detail));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
it("consulta dez aulas e oferece matrícula explícita sem certificado", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.querySelectorAll('input[type="date"]')).toHaveLength(10);
  expect(button("Criar currículo")).toBeDefined(); expect(button("Criar turma")).toBeDefined();
  expect(button("Matricular")).toBeDefined(); expect(container.textContent).not.toMatch(/Certificar/);
  expect(state.request.mock.calls.every(c => c[2] === "GET")).toBe(true);
});
it("responsável pode matricular sem carregar catálogo ou equipe", async () => {
  state.roles = ["lider_consol"]; await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Criar turma")).toBeUndefined(); expect(button("Salvar calendário")).toBeUndefined();
  expect(button("Encerrar turma")).toBeUndefined();
  expect(button("Matricular")).toBeDefined();
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
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path === "/curriculos" || path.endsWith("/matriculas") ? [] : { ...detail, encerrada: true }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Reabrir turma")).toBeDefined();
  expect(container.querySelector<HTMLFieldSetElement>(".uv-detail fieldset")?.disabled).toBe(true);
});
it("erro de transporte é recuperável", async () => {
  state.request.mockRejectedValueOnce(new Error("Falha de conexão")); await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Falha de conexão"); expect(button("Atualizar")?.disabled).toBe(false);
});

it("matricula pessoa elegível com comando explícito e atualiza a lista", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
  const select = Array.from(container.querySelectorAll("select")).find(s => s.textContent?.includes("Pessoa elegível"))!;
  await act(async () => { select.value = "p"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { button("Matricular")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas", "POST", { id: expect.any(String), pessoa_id: "p" }, expect.any(AbortSignal));
  expect(container.textContent).toContain("Matrícula registrada.");
});
it("cancelamento exige confirmação e preserva consulta", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path.endsWith("/matriculas") ? [{ id: "mat", pessoa_id: "p", nome: "Aluno", ativa: true, origem_aptidao: "legado" }] : path === "/curriculos" || path === "/opcoes" || path.split("?")[0].endsWith("/elegiveis") ? [] : detail));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Cancelar matrícula de Aluno")!.click(); });
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => { button("Confirmar cancelamento")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas/mat/cancelar", "POST", undefined, expect.any(AbortSignal));
});
it("consulta elegíveis com pré-requisito em módulos posteriores", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path === "/curriculos" || path === "/opcoes" || path.endsWith("/matriculas") || path.endsWith("/elegiveis") ? [] : { ...detail, modulo: { ...modulo, numero: 2 } }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Matricular")).toBeDefined();
  expect(state.request.mock.calls.some(c => c[1].endsWith("/elegiveis"))).toBe(true);
});
it("reativação reutiliza identificador da matrícula cancelada", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path.endsWith("/matriculas") ? [{ id: "anterior", pessoa_id: "p", nome: "Pessoa elegível", ativa: false, origem_aptidao: "legado" }] : path.split("?")[0].endsWith("/elegiveis") ? [{ id: "p", nome: "Pessoa elegível" }] : path === "/curriculos" || path === "/opcoes" ? [] : detail));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  const select = Array.from(container.querySelectorAll("select")).find(s => s.textContent?.includes("Pessoa elegível"))!;
  await act(async () => { select.value = "p"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { button("Matricular")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas", "POST", { id: "anterior", pessoa_id: "p" }, expect.any(AbortSignal));
});
it("recusa do servidor aparece sem anunciar matrícula registrada", async () => {
  const normal = state.request.getMockImplementation()!;
  state.request.mockImplementation((...args) => args[2] === "POST" ? Promise.reject(new Error("Matrícula exige aptidão à CD com origem identificada")) : normal(...args));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  const select = Array.from(container.querySelectorAll("select")).find(s => s.textContent?.includes("Pessoa elegível"))!;
  await act(async () => { select.value = "p"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { button("Matricular")!.click(); });
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("origem identificada");
  expect(container.textContent).not.toContain("Matrícula registrada.");
  expect(button("Matricular")!.disabled).toBe(false);
});

it("mostra pessoa arquivada e mantém cancelamento disponível", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "/turmas" ? [turma] : path.endsWith("/matriculas") ? [{ id: "mat", pessoa_id: "p", nome: "Aluno", pessoa_arquivada: true, ativa: true, origem_aptidao: "legado" }] : path === "/curriculos" || path === "/opcoes" || path.split("?")[0].endsWith("/elegiveis") ? [] : detail));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.textContent).toContain("Pessoa arquivada");
  expect(button("Cancelar matrícula de Aluno")?.disabled).toBe(false);
});
it("busca elegíveis por nome e oferece paginação", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.querySelector('input[type="search"]')).not.toBeNull();
  await act(async () => { button("Buscar pessoas")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/elegiveis?q=&limit=100&offset=0", "GET", undefined, expect.any(AbortSignal));
  expect(button("Página anterior")?.disabled).toBe(true);
});

it("abre chamada e histórico com autor, corrige com revisão explícita", async () => {
  const normal = state.request.getMockImplementation()!;
  state.request.mockImplementation((...args) => args[1].endsWith("/matriculas") ? Promise.resolve([{ id: "mat", pessoa_id: "p", nome: "Aluno", ativa: true, origem_aptidao: "legado" }]) : args[1].endsWith("/historico") ? Promise.resolve([{ registro_id: "anterior", anterior_id: null, presente: false, modalidade: "regular", registrada_por_nome: "Ana Sintética", registrada_em: "2026-10-01T12:00:00Z" }]) : normal(...args));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Chamada de Aluno")!.click(); });
  expect(container.textContent).toContain("Ana Sintética");
  expect(container.textContent).toContain("Ausente");
  await act(async () => { button("Registrar reposição")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas/mat/presencas/a0", "POST", { id: expect.any(String), anterior_id: "anterior", presente: true, modalidade: "reposicao" }, expect.any(AbortSignal));
});

it("preserva revisão e chave quando a atualização após gravação falha", async () => {
  const normal = state.request.getMockImplementation()!;
  let historyCalls = 0;
  state.request.mockImplementation((...args) => {
    if (args[1].endsWith("/matriculas")) return Promise.resolve([{ id: "mat", nome: "Aluno", ativa: true, origem_aptidao: "legado" }]);
    if (args[1].endsWith("/historico")) {
      historyCalls++;
      return historyCalls === 1 ? Promise.resolve([{ registro_id: "old", presente: false, modalidade: "regular", registrada_por_nome: "Ana Sintética", registrada_em: "2026-10-01T12:00:00Z" }]) : Promise.reject(new Error("Consulta indisponível"));
    }
    return normal(...args);
  });
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Chamada de Aluno")!.click(); });
  await act(async () => { button("Registrar reposição")!.click(); });
  expect(container.textContent).toContain("Ana Sintética");
  await act(async () => { button("Registrar reposição")!.click(); });
  const posts = state.request.mock.calls.filter(c => c[2] === "POST");
  expect(posts).toHaveLength(2); expect(posts[1]![3]).toEqual(posts[0]![3]);
});

it.each(["encerrada", "cancelada"])("mantém histórico para consulta com turma/matrícula %s", async (status) => {
  const normal = state.request.getMockImplementation()!;
  state.request.mockImplementation((...args) => args[1].endsWith("/matriculas") ? Promise.resolve([{ id: "mat", nome: "Aluno", ativa: status !== "cancelada", origem_aptidao: "legado" }]) : args[1].endsWith("/historico") ? Promise.resolve([]) : args[1] === "/turmas/turma" ? Promise.resolve({ ...detail, encerrada: status === "encerrada" }) : normal(...args));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Chamada de Aluno")!.click(); });
  expect(button("Registrar presença")!.closest("fieldset")!.disabled).toBe(true);
  expect(button("Atualizar histórico")!.disabled).toBe(false);
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
});


function completionFixture(completed = false) {
  const normal = state.request.getMockImplementation()!;
  state.request.mockImplementation((...args) => args[1].endsWith("/matriculas") ? Promise.resolve([{ id: "mat", pessoa_id: "p", nome: "Aluno", ativa: true, origem_aptidao: "legado", conclusao: completed ? { id: "done", origem: "frequencia", confirmada_por: "autor", confirmada_em: "2026-10-01T12:00:00Z" } : null }]) : args[1] === "/pessoas/p/curriculos/c" ? Promise.resolve({ conclusoes: [], niveis_concluidos: ["nivel"], certificados: [{ id: "cert", codigo: "codigo", nome_pessoa: "Nome no certificado", nome_curriculo: "Currículo original", versao_curriculo: "1", emitida_por: "autor", emitida_em: "2026-10-01T12:00:00Z", revogada: false }] }) : normal(...args));
}
it("conclusão exige confirmação humana e envia chave idempotente", async () => {
  completionFixture(); await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Concluir módulo de Aluno")!.click(); });
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => { button("Confirmar conclusão")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas/mat/conclusao", "POST", { id: expect.any(String), confirmado: true }, expect.any(AbortSignal));
});
it("equivalência exige evidência e só aparece para coordenação", async () => {
  state.roles = ["lider_consol"]; completionFixture(); await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Concluir módulo de Aluno")).toBeDefined();
  expect(button("Registrar equivalência de Aluno")).toBeUndefined();
  expect(button("Certificados de Aluno")).toBeUndefined();
});
it("matrícula concluída preserva histórico e bloqueia cancelamento", async () => {
  completionFixture(true); await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.textContent).toContain("Concluída");
  expect(button("Cancelar matrícula de Aluno")).toBeUndefined();
  expect(button("Concluir módulo de Aluno")).toBeUndefined();
  expect(button("Chamada de Aluno")).toBeDefined();
});
it("consulta snapshot e exige motivo para revogar certificado", async () => {
  completionFixture(true);
  const normal = state.request.getMockImplementation()!;
  state.request.mockImplementation((...args) => args[1] === "/turmas/turma" ? Promise.resolve({ ...detail, curriculo_id: "c" }) : normal(...args));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Certificados de Aluno")!.click(); });
  expect(container.textContent).toContain("Nome no certificado");
  expect(container.textContent).toContain("Currículo original");
  await act(async () => { button("Revogar certificado")!.click(); });
  expect(button("Confirmar revogação")!.disabled).toBe(true);
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
});

it("registra equivalência com evidência curta após confirmação", async () => {
  completionFixture(); await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Registrar equivalência de Aluno")!.click(); });
  expect(button("Confirmar equivalência")!.disabled).toBe(true);
  const input = container.querySelector<HTMLTextAreaElement>("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "Documento conferido");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { button("Confirmar equivalência")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turmas/turma/matriculas/mat/equivalencia", "POST", { id: expect.any(String), confirmado: true, evidencia: "Documento conferido" }, expect.any(AbortSignal));
});
it("emite certificado somente após confirmação e envia revogação com motivo", async () => {
  completionFixture(true);
  const normal = state.request.getMockImplementation()!;
  let emitted = false;
  state.request.mockImplementation((...args) => {
    if (args[1] === "/turmas/turma") return Promise.resolve({ ...detail, curriculo_id: "c" });
    if (args[1] === "/pessoas/p/curriculos/c" && !emitted) return Promise.resolve({ conclusoes: [], niveis_concluidos: [], certificados: [] });
    if (args[1] === "/pessoas/p/curriculos/c/certificados" && args[2] === "POST") emitted = true;
    return normal(...args);
  });
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Certificados de Aluno")!.click(); });
  await act(async () => { button("Emitir certificado")!.click(); });
  expect(state.request.mock.calls.some(c => c[2] === "POST")).toBe(false);
  await act(async () => { button("Confirmar emissão")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/pessoas/p/curriculos/c/certificados", "POST", { id: expect.any(String), confirmado: true }, expect.any(AbortSignal));
  await act(async () => { button("Revogar certificado")!.click(); });
  const input = container.querySelector<HTMLTextAreaElement>("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "Correção administrativa");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { button("Confirmar revogação")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/certificados/cert/revogar", "POST", { motivo: "Correção administrativa" }, expect.any(AbortSignal));
});
