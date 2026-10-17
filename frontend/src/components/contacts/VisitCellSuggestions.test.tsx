// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { VisitCellSuggestions } from "./VisitCellSuggestions";
const mocks = vi.hoisted(() => ({read: vi.fn(), confirm: vi.fn(), expire: vi.fn(), roles: ["pastor"]}));
vi.mock("@/lib/auth-context", () => ({useAuth: () => ({token: "synthetic", user: {roles: mocks.roles}, expireSession: mocks.expire})}));
vi.mock("@/lib/visit-cell-api", () => ({readVisitSuggestions: mocks.read, confirmVisitCell: mocks.confirm}));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const item = {pessoa_id: "p1", pessoa_nome: "Pessoa sintética", evento_id: "e1", celula_id: "c1", celula_nome: "Célula sintética", data_ocorrencia: "2026-10-16T19:00:00Z", revision: "revision", blocked_reason: null, already_linked: false};
beforeEach(() => {
  vi.clearAllMocks(); mocks.roles = ["pastor"];
  mocks.read.mockResolvedValue({items: [item], page: 1, page_size: 20, total: 21});
  mocks.confirm.mockResolvedValue(undefined);
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {configurable: true, get() {return this.parentElement;}});
});
afterEach(() => {act(() => root.unmount()); container.remove();});
async function render(personId?: string) {await act(async () => root.render(<VisitCellSuggestions personId={personId} />));}
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(b => b.textContent === label)!;
  expect(button).toBeDefined(); await act(async () => button.click());
}
it("Pessoa mostra sugestão sem escrever e só confirma após revisão explícita", async () => {
  await render("p1"); expect(mocks.read).toHaveBeenCalledWith("synthetic", "p1", 1);
  expect(mocks.confirm).not.toHaveBeenCalled();
  await click("Revisar vínculo"); expect(mocks.confirm).not.toHaveBeenCalled();
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain("Ao confirmar, o acompanhamento será marcado como consolidado");
  await click("Confirmar vínculo"); expect(mocks.confirm).toHaveBeenCalledExactlyOnceWith("synthetic", item);
  expect(container.textContent).toContain("Vínculo confirmado");
});
it("Central pagina no servidor", async () => {
  await render(); await click("Próxima");
  expect(mocks.read).toHaveBeenLastCalledWith("synthetic", undefined, 2);
});
it("mostra indisponibilidade sem permitir confirmação", async () => {
  mocks.read.mockResolvedValue({items: [{...item, blocked_reason: "Célula inativa"}], page: 1, page_size: 20, total: 1});
  await render(); expect(container.textContent).toContain("Célula inativa");
  expect([...container.querySelectorAll("button")].find(b => b.textContent === "Revisar vínculo")?.disabled).toBe(true);
});
it("recusa do servidor preserva o contexto e permite atualizar", async () => {
  mocks.confirm.mockRejectedValue(new Error("Evidência alterada. Atualize a sugestão."));
  await render(); await click("Revisar vínculo"); await click("Confirmar vínculo");
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain("Evidência alterada");
  await click("Cancelar"); await click("Atualizar sugestões"); expect(mocks.read).toHaveBeenCalledTimes(2);
});
it("líder e operador não consultam sugestões", async () => {
  mocks.roles = ["lider_celula", "operador"]; await render("p1");
  expect(container.textContent).toBe(""); expect(mocks.read).not.toHaveBeenCalled();
});

it("falha ao atualizar cadastro após commit permite tentar a leitura sem repetir confirmação", async () => {
  const onConfirmed = vi.fn().mockRejectedValueOnce(new Error("Leitura indisponível")).mockResolvedValue(undefined);
  await act(async () => root.render(<VisitCellSuggestions personId="p1" onConfirmed={onConfirmed} />));
  await click("Revisar vínculo"); await click("Confirmar vínculo");
  expect(container.textContent).toContain("O vínculo foi confirmado, mas não foi possível atualizar o cadastro");
  await click("Atualizar cadastro");
  expect(onConfirmed).toHaveBeenCalledTimes(2);
  expect(mocks.confirm).toHaveBeenCalledTimes(1);
  expect(container.textContent).not.toContain("não foi possível atualizar o cadastro");
});
