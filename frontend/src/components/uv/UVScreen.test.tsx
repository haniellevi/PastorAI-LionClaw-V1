// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { UVScreen } from "./UVScreen";

const state = vi.hoisted(() => ({ request: vi.fn(), roles: ["admin"] }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ token: "synthetic", user: { roles: state.roles, churchId: "church", appUserId: "user" } }) }));
vi.mock("@/lib/uv-api", () => ({ uvRequest: (...args: unknown[]) => state.request(...args) }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root;
const turma = { id: "turma", nome: "Turma teste", encerrada: false };
const detail = { ...turma, atividades: [], responsaveis: [], matriculas: [{ id: "m", pessoa_id: "p", nome: "Pessoa sintética", conexao_celula_pendente: true }] };
const button = (text: string) => Array.from(container.querySelectorAll("button")).find(b => b.textContent?.includes(text));
async function render() { await act(async () => { root.render(h(UVScreen)); }); }
beforeEach(() => {
  state.roles = ["admin"]; state.request.mockReset();
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "" ? [turma] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : detail));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

it("consulta turma e expõe nove datas, pendência e matrícula explícita", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.querySelectorAll('input[type="date"]')).toHaveLength(9);
  expect(container.textContent).toContain("Conexão à célula pendente");
  expect(button("Matricular pessoa")?.disabled).toBe(true);
  expect(state.request.mock.calls.every(call => call[2] === "GET")).toBe(true);
});

it("recusa papel sem acesso antes de consultar dados", async () => {
  state.roles = ["operador"]; await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Acesso restrito");
  expect(state.request).not.toHaveBeenCalled();
});

it("erro recuperável mantém atualização disponível", async () => {
  state.request.mockRejectedValueOnce(new Error("Acesso revogado")); await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Acesso revogado");
  expect(button("Atualizar turmas")?.disabled).toBe(false);
});

it("turma encerrada mantém consulta e desabilita formulários", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "" ? [{ ...turma, encerrada: true }] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : { ...detail, encerrada: true }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(Array.from(container.querySelectorAll("fieldset")).every(f => f.disabled)).toBe(true);
  expect(button("Matricular pessoa")?.disabled).toBe(true);
  expect(button("Encerrar turma")).toBeUndefined();
});

it("encerramento exige confirmação e só depois envia mutação", async () => {
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Encerrar turma")!.click(); });
  expect(container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(state.request.mock.calls.some(call => call[2] === "POST")).toBe(false);
  await act(async () => { button("Confirmar encerramento")!.click(); });
  expect(state.request).toHaveBeenCalledWith("synthetic", "/turma/encerrar", "POST", undefined, expect.any(AbortSignal));
});

it("responsável consulta sem buscar equipe nem oferecer ações de coordenação", async () => {
  state.roles = ["lider_consol"];
  await render();
  expect(state.request.mock.calls.some(call => String(call[1]).includes("opcoes"))).toBe(false);
  await act(async () => { button("Turma teste")!.click(); });
  expect(button("Salvar responsáveis")).toBeUndefined();
  expect(button("Encerrar turma")).toBeUndefined();
  expect(state.request.mock.calls.some(call => String(call[1]).includes("finalidade=usuarios"))).toBe(false);
});

it("mostra chamada só das oito aulas e registra reposição explícita", async () => {
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "" ? [turma] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : { ...detail,
    atividades: [{ ordem: 1, tipo: "aula", aula: 1, data: "2026-10-01" }, { ordem: 5, tipo: "encontro", aula: null, data: "2026-10-15" }],
    matriculas: [{ ...detail.matriculas[0], aulas_cumpridas: [], aulas_pendentes: [1,2,3,4,5,6,7,8], presencas: [] }] }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(container.textContent).toContain("Chamada de presença");
  expect(container.textContent).toContain("Pendentes: 1, 2, 3, 4, 5, 6, 7, 8");
  const lesson = container.querySelector<HTMLSelectElement>('select[aria-label="Aula da chamada"]')!;
  expect(Array.from(lesson.options).map(o => o.textContent)).not.toContain("Encontro");
  const modality = container.querySelector<HTMLSelectElement>('select[aria-label="Modalidade da presença"]')!;
  await act(async () => { const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!; setter.call(modality, "reposicao"); modality.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { button("Registrar presença")!.click(); });
  expect(state.request.mock.calls.some(c => c[1] === "/turma/matriculas/m/presencas/1" && c[2] === "POST" && c[3].modalidade === "reposicao" && c[3].presente === true)).toBe(true);
});

it("correção exige confirmação e envia a versão anterior; consulta mostra auditoria", async () => {
  const revision = { aula: 1, registro_id: "previous", presente: false, modalidade: "regular", registrada_por: "equipe", registrada_em: "2026-10-17T12:00:00Z" };
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "" ? [turma] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : String(path).endsWith("/historico") ? [{ ...revision, anterior_id: null }] : { ...detail,
    atividades: [{ ordem: 1, tipo: "aula", aula: 1, data: "2026-10-01" }],
    matriculas: [{ ...detail.matriculas[0], aulas_cumpridas: [], aulas_pendentes: [1,2,3,4,5,6,7,8], presencas: [revision] }] }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  expect(button("Salvar correção")!.disabled).toBe(true);
  const checkbox = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).find(c => c.parentElement?.textContent?.includes("Confirmo a correção"))!;
  await act(async () => { checkbox.click(); });
  await act(async () => { button("Salvar correção")!.click(); });
  expect(state.request.mock.calls.some(c => c[2] === "POST" && c[3]?.anterior_id === "previous")).toBe(true);
  await act(async () => { button("Consultar histórico")!.click(); });
  expect(container.textContent).toContain("Registro inicial: Ausente");
  expect(container.textContent).toContain("Usuário equipe");
});

it("falha de transporte preserva a chave da chamada na repetição", async () => {
  let failed = false;
  state.request.mockImplementation((_token, path, method) => {
    if (method === "POST" && !failed) { failed = true; return Promise.reject(new Error("Falha de conexão")); }
    return Promise.resolve(path === "" ? [turma] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : { ...detail,
      atividades: [{ ordem: 1, tipo: "aula", aula: 1, data: "2026-10-01" }],
      matriculas: [{ ...detail.matriculas[0], aulas_cumpridas: [], aulas_pendentes: [1,2,3,4,5,6,7,8], presencas: [] }] });
  });
  await render(); await act(async () => { button("Turma teste")!.click(); });
  await act(async () => { button("Registrar presença")!.click(); });
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Falha de conexão");
  await act(async () => { button("Registrar presença")!.click(); });
  const posts = state.request.mock.calls.filter(c => c[2] === "POST");
  expect(posts).toHaveLength(2);
  expect(posts[0]![3].id).toBe(posts[1]![3].id);
});

it("inicia a correção com o registro atual e sincroniza ao trocar de aula", async () => {
  const records = [
    { aula: 1, registro_id: "first", presente: false, modalidade: "reposicao", registrada_por: "equipe", registrada_em: "2026-10-17T12:00:00Z" },
    { aula: 2, registro_id: "second", presente: true, modalidade: "regular", registrada_por: "equipe", registrada_em: "2026-10-17T13:00:00Z" },
  ];
  state.request.mockImplementation((_token, path) => Promise.resolve(path === "" ? [turma] : String(path).startsWith("/opcoes") ? { pessoas: [], usuarios: [] } : { ...detail,
    atividades: records.map(r => ({ ordem: r.aula, tipo: "aula", aula: r.aula, data: "2026-10-01" })),
    matriculas: [{ ...detail.matriculas[0], aulas_cumpridas: [2], aulas_pendentes: [1,3,4,5,6,7,8], presencas: records }] }));
  await render(); await act(async () => { button("Turma teste")!.click(); });
  const status = () => container.querySelector<HTMLSelectElement>('.uv-student fieldset select:not([aria-label])')!;
  const modality = () => container.querySelector<HTMLSelectElement>('select[aria-label="Modalidade da presença"]')!;
  expect(status().value).toBe("false");
  expect(modality().value).toBe("reposicao");
  const lesson = container.querySelector<HTMLSelectElement>('select[aria-label="Aula da chamada"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(lesson, "2");
    lesson.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(status().value).toBe("true");
  expect(modality().value).toBe("regular");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(lesson, "1");
    lesson.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(status().value).toBe("false");
  expect(modality().value).toBe("reposicao");
  const checkbox = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).find(c => c.parentElement?.textContent?.includes("Confirmo a correção"))!;
  await act(async () => { checkbox.click(); });
  await act(async () => { button("Salvar correção")!.click(); });
  expect(state.request.mock.calls.find(c => c[2] === "POST")?.[3]).toMatchObject({ presente: false, modalidade: "reposicao", anterior_id: "first" });
});
