// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ link: vi.fn(), lookup: vi.fn(), saved: vi.fn(), close: vi.fn(), session: vi.fn() }));
vi.mock("@/lib/team-api", () => ({ linkPessoa: mocks.link }));
vi.mock("@/lib/lookup-api", () => ({ fetchContactLookupPage: mocks.lookup }));
import { TeamPessoaDialog } from "./TeamPessoaDialog";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const person = { id: "p-synthetic", nome: "Pessoa sintética" };
const member = { usuarioId: "u-synthetic", nome: "Conta sintética", email: "synthetic@example.test", status: "ativo", papeis: ["admin"], pessoaId: "p-old" };
async function flush() { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); }
function button(label: string) { return Array.from(container.querySelectorAll("button")).find(b => b.textContent === label)!; }
async function render() {
  await act(async () => root.render(h(TeamPessoaDialog, { member, token: "synthetic-token", onClose: mocks.close, onSaved: mocks.saved, onSessionError: mocks.session })));
  await flush();
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.link.mockResolvedValue({ usuarioId: member.usuarioId, pessoaId: person.id });
  mocks.lookup.mockResolvedValue({ items: [person], page: 1, pageSize: 25, total: 1 });
  mocks.session.mockReturnValue(false);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

it("seleciona Pessoa, salva somente vínculo e informa conclusão", async () => {
  await render();
  expect(container.querySelector('label[for="team-pessoa-query"]')?.textContent).toBe("Buscar Pessoa");
  expect(button("Salvar vínculo").disabled).toBe(true);
  act(() => button(person.nome).click());
  expect(button(person.nome).getAttribute("aria-pressed")).toBe("true");
  await act(async () => button("Salvar vínculo").click());
  expect(mocks.link).toHaveBeenCalledWith("synthetic-token", member.usuarioId, person.id);
  expect(mocks.saved).toHaveBeenCalledOnce();
});
it("desvincula com null explícito", async () => {
  await render(); await act(async () => button("Desvincular Pessoa").click());
  expect(mocks.link).toHaveBeenCalledWith("synthetic-token", member.usuarioId, null);
});
it("mostra erro do servidor e permite tentar novamente", async () => {
  mocks.link.mockRejectedValue(new Error("Pessoa já vinculada"));
  await render(); act(() => button(person.nome).click());
  await act(async () => button("Salvar vínculo").click());
  expect(container.querySelector('[role="alert"]')?.textContent).toBe("Pessoa já vinculada");
  expect(button("Salvar vínculo").disabled).toBe(false);
  expect(mocks.saved).not.toHaveBeenCalled();
});
it("bloqueia ações durante gravação e fecha somente após resposta", async () => {
  let resolve!: (value: unknown) => void;
  mocks.link.mockReturnValue(new Promise(r => { resolve = r; }));
  await render(); act(() => button(person.nome).click());
  act(() => button("Salvar vínculo").click()); await flush();
  expect(button("Salvando…").disabled).toBe(true);
  expect(button("Cancelar").disabled).toBe(true);
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(mocks.close).not.toHaveBeenCalled();
  await act(async () => resolve({})); expect(mocks.saved).toHaveBeenCalledOnce();
});
it("exibe falha e recuperação da busca", async () => {
  mocks.lookup.mockRejectedValueOnce(new Error("indisponível"));
  await render();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Não foi possível buscar Pessoas");
  await act(async () => button("Tentar novamente").click()); await flush();
  expect(button(person.nome)).toBeTruthy();
});
