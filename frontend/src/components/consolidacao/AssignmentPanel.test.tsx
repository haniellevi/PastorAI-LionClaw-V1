// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { TeamLookupMember } from "@/lib/dashboard-api";
import type { AssignmentTrack } from "@/lib/consolidacao-api";

const state = vi.hoisted(() => ({ self: "candidate", roles: ["lider_celula"], fetch: vi.fn(), answer: vi.fn(), assign: vi.fn(), expire: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ token: "synthetic-token", user: { appUserId: state.self, roles: state.roles }, expireSession: state.expire }) }));
vi.mock("@/lib/consolidacao-api", async original => ({ ...await original<typeof import("@/lib/consolidacao-api")>(), fetchAssignments: state.fetch, answerInvitation: state.answer, assignConsolidador: state.assign }));
const { AssignmentPanel } = await import("./AssignmentPanel");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const track: AssignmentTrack = { id: "track", pessoaId: "person", pessoaNome: "Pessoa fictícia", responsavelId: "old", prazoConexao: null, etapasConfirmadas: [], tiposNecessarios: ["fonovisita"], convite: { id: "invite", consolidacaoId: "track", responsavelId: "candidate", status: "atribuida", prazoAceite: "2026-10-18T18:00:00Z", autoatribuicao: false } };
beforeEach(() => {
  vi.clearAllMocks();
  state.self = "candidate"; state.roles = ["lider_celula"];
  state.fetch.mockResolvedValue({ items: [track], nextCursor: null });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = async (team: TeamLookupMember[] = []) => { await act(async () => { root.render(<AssignmentPanel team={team} />); }); };
const button = (text: string) => Array.from(container.querySelectorAll("button")).find(el => el.textContent?.includes(text));
it.each([true, false])("destinatário responde ao convite, aceite=%s", async aceitar => {
  state.answer.mockResolvedValue({ ...track.convite, status: aceitar ? "aceita" : "recusada" });
  await render();
  expect(container.textContent).toContain("Responsável atual");
  await act(async () => { button(aceitar ? "Aceitar fonovisita" : "Recusar convite")!.click(); });
  expect(state.answer).toHaveBeenCalledWith("synthetic-token", track.convite, aceitar);
  expect(state.fetch).toHaveBeenCalledTimes(2);
  expect(container.querySelector('[role="status"]')?.textContent).toContain(aceitar ? "Convite aceito" : "Convite recusado");
});
it("coordenação supervisiona sem aceitar pelo destinatário", async () => {
  state.self = "coordinator"; state.roles = ["pastor"];
  await render();
  expect(container.textContent).toContain("Aguardando aceite");
  expect(button("Aceitar fonovisita")).toBeUndefined();
  expect(button("Recusar convite")).toBeUndefined();
});
it("resposta expirada informa coordenação sem anunciar aceite", async () => {
  state.answer.mockResolvedValue({ ...track.convite, status: "expirada" });
  await render();
  await act(async () => { button("Aceitar fonovisita")!.click(); });
  expect(container.querySelector('[role="status"]')?.textContent).toContain("O prazo de aceite expirou");
});
it("falha mantém o convite e oferece nova leitura", async () => {
  state.answer.mockRejectedValue(new Error("synthetic failure"));
  await render();
  await act(async () => { button("Aceitar fonovisita")!.click(); });
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(button("Atualizar convites")?.disabled).toBe(false);
  expect(container.textContent).toContain("Aguardando aceite");
});

it("cursor do servidor alcança convite válido após página expirada vazia", async () => {
  state.fetch.mockResolvedValueOnce({ items: [], nextCursor: "stable-cursor" })
    .mockResolvedValueOnce({ items: [track], nextCursor: null });
  await render();
  expect(container.textContent).toContain("Há mais registros");
  await act(async () => { button("Carregar mais convites")!.click(); });
  expect(state.fetch).toHaveBeenLastCalledWith("synthetic-token", "stable-cursor");
  expect(button("Aceitar fonovisita")).toBeDefined();
});

it("convite exige candidato capaz de todos os tipos ativos da trilha", async () => {
  state.self = "coordinator"; state.roles = ["pastor"];
  state.fetch.mockResolvedValue({ items: [{ ...track, tiposNecessarios: ["fonovisita", "conectar_celula"] }], nextCursor: null });
  const base = { email: "", status: "ativo", pessoaId: "synthetic-person", papeis: [] };
  await render([
    { ...base, usuarioId: "cell-leader", nome: "Só fonovisita", tiposFila: ["fonovisita"] },
    { ...base, usuarioId: "capable", nome: "Apto para toda a trilha", tiposFila: ["fonovisita", "conectar_celula"] },
  ]);
  const options = Array.from(container.querySelectorAll("option")).map(option => option.textContent);
  expect(options).not.toContain("Só fonovisita");
  expect(options).toContain("Apto para toda a trilha");
  expect(button("Registrar convite")?.disabled).toBe(true);
  await act(async () => {
    const select = container.querySelector("select")!;
    select.value = "capable"; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(button("Registrar convite")?.disabled).toBe(false);
  await act(async () => { button("Registrar convite")!.click(); });
  expect(state.assign).toHaveBeenCalledWith("synthetic-token", "track", "capable");
});
