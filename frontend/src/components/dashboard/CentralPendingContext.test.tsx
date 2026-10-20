// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CentralPendingContext } from "./CentralPendingContext";

const api = vi.hoisted(() => ({ getDashboard: vi.fn() }));
vi.mock("@/lib/cell-central-api", () => ({ getDashboard: api.getDashboard }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const onNavigate = vi.fn();
const onSessionError = vi.fn();
const counts = {
  relatorios_pendentes: 3, solicitacoes_aguardando: 2,
  celulas_com_alerta: 1, multiplicacoes_pendentes: 1,
  avisos_recentes: 8, materiais_recentes: 9,
};
beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.getDashboard.mockResolvedValue(counts);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
async function render(token = "synthetic-a") {
  await act(async () => { root.render(h(CentralPendingContext, { token, onNavigate, onSessionError })); });
}
it("compõe contadores sem somar multiplicações duas vezes e navega à Central", async () => {
  await render();
  expect(api.getDashboard).toHaveBeenCalledWith("synthetic-a");
  expect(container.textContent).toContain("3 relatórios pendentes");
  expect(container.textContent).toContain("2 solicitações aguardando");
  expect(container.textContent).toContain("1 célula com alerta");
  expect(container.textContent).not.toContain("8");
  const link = container.querySelector("a")!;
  expect(link.getAttribute("href")).toBe("#central-celula");
  act(() => link.click());
  expect(onNavigate).toHaveBeenCalledWith("central-celula");
});
it("mostra vazio só depois de uma leitura bem-sucedida", async () => {
  api.getDashboard.mockResolvedValue({ ...counts, relatorios_pendentes: 0, solicitacoes_aguardando: 0, celulas_com_alerta: 0 });
  await render();
  expect(container.textContent).toContain("Nenhuma pendência da Central agora.");
});
it("mostra falha sem falso vazio e permite tentar novamente", async () => {
  api.getDashboard.mockRejectedValueOnce(new Error("simulado"));
  await render();
  expect(container.textContent).toContain("Pendências da Central indisponíveis");
  expect(container.textContent).not.toContain("Nenhuma pendência");
  await act(async () => { container.querySelector("button")!.click(); });
  expect(api.getDashboard).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain("3 relatórios pendentes");
});
it("descarta resposta antiga após trocar a sessão", async () => {
  let resolveOld!: (value: typeof counts) => void;
  api.getDashboard.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await render();
  expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  await render("synthetic-b");
  await act(async () => { resolveOld({ ...counts, relatorios_pendentes: 99 }); });
  expect(container.textContent).not.toContain("99");
  expect(container.textContent).toContain("3 relatórios pendentes");
});

it("encaminha expiração ao fluxo de sessão existente", async () => {
  const expired = new Error("sessão sintética expirada");
  api.getDashboard.mockRejectedValueOnce(expired);
  await render();
  expect(onSessionError).toHaveBeenCalledWith(expired);
});
it("não trata falha de sessão antiga após desmontar", async () => {
  let rejectOld!: (error: unknown) => void;
  api.getDashboard.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
  await render();
  act(() => root.render(null));
  await act(async () => { rejectOld(new Error("sessão antiga")); });
  expect(onSessionError).not.toHaveBeenCalled();
});
it("preserva gestos nativos de abrir o link em outra aba", async () => {
  await render();
  const click = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
  act(() => { container.querySelector("a")!.dispatchEvent(click); });
  expect(click.defaultPrevented).toBe(false);
  expect(onNavigate).not.toHaveBeenCalled();
});
