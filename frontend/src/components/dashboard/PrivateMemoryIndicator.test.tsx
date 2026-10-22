// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionExpiredError } from "@/lib/api";
import { PrivateMemoryIndicator } from "./PrivateMemoryIndicator";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/dashboard-api", () => ({ authedFetch: api.fetch }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
const onSessionError = vi.fn();
const counts = {
  pedidos_exclusao: {
    pendentes: 6, atendidos: 2, recusados: 1, mais_antigo_segundos: 259201,
    faixas_idade: { menos_24h: 3, de_1_a_3_dias: 2, mais_3_dias: 1 },
  },
  resumos_ativos: 4, retomadas_entregues: 8,
  tarefas_resumo: { queued: 2, running: 1, done: 5, refused: 3 },
  limpezas_privadas: { pendente: 7, concluida: 9 },
};
beforeEach(() => {
  vi.resetAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.fetch.mockResolvedValue(Response.json(counts));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
async function render(token = "synthetic-a") {
  await act(async () => { root.render(h(PrivateMemoryIndicator, { token, onSessionError })); });
}

it("mostra texto, faixas e contagens sem afirmar que a limpeza terminou", async () => {
  await render();
  expect(api.fetch).toHaveBeenCalledWith("synthetic-a", "/operations/private-memory", {
    cache: "no-store", signal: expect.any(AbortSignal),
  });
  expect(container.textContent).toContain("6 pedidos de exclusão pendentes");
  expect(container.textContent).toContain("2 atendidos e 1 recusados");
  expect(container.textContent).toContain("mais antigo: 3 d e 0 h");
  expect(container.textContent).toContain("Menos de 24 h: 3");
  expect(container.textContent).toContain("De 1 a 3 dias: 2");
  expect(container.textContent).toContain("Mais de 3 dias: 1");
  expect(container.textContent).toContain("a limpeza pode continuar pendente");
  expect(container.querySelector("details")?.textContent).toContain("Retomadas entregues no acervo atual: 8");
  expect(container.querySelector("details")?.textContent).toContain("Na fila: 2");
  expect(container.querySelector("details")?.textContent).toContain("Em execução: 1");
  expect(container.querySelector("details")?.textContent).toContain("7 pendentes e 9 concluídas");
});

it("oferece link nativo e controles focáveis pelo teclado", async () => {
  await render();
  const link = container.querySelector("a")!;
  expect(link.getAttribute("href")).toBe("#inbox");
  expect(link.textContent).toBe("Decidir pedidos no Atendimento");
  expect(link.tabIndex).toBe(0);
  link.focus();
  expect(document.activeElement).toBe(link);
  const summary = container.querySelector("summary")!;
  summary.focus();
  expect(document.activeElement).toBe(summary);
  const button = container.querySelector("button")!;
  button.focus();
  expect(document.activeElement).toBe(button);
  expect(button.disabled).toBe(false);
});

it("mostra zero somente após leitura bem-sucedida", async () => {
  api.fetch.mockResolvedValue(Response.json({ ...counts, pedidos_exclusao: {
    ...counts.pedidos_exclusao, pendentes: 0, mais_antigo_segundos: null,
    faixas_idade: { menos_24h: 0, de_1_a_3_dias: 0, mais_3_dias: 0 },
  } }));
  await render();
  expect(container.textContent).toContain("Nenhum pedido de exclusão pendente");
  expect(container.textContent).not.toContain("mais antigo");
});

it.each([403, 404, 503])("trata HTTP %s como indisponível e permite atualizar", async status => {
  api.fetch.mockResolvedValueOnce(Response.json({}, { status }));
  await render();
  expect(container.textContent).toContain("Contagens da memória indisponíveis");
  expect(container.textContent).not.toContain("Nenhum pedido");
  await act(async () => { container.querySelector("button")!.click(); });
  expect(container.textContent).toContain("6 pedidos de exclusão pendentes");
  expect(api.fetch).toHaveBeenCalledTimes(2);
});

it("descarta dados da sessão anterior e aborta a leitura", async () => {
  let resolveOld!: (response: Response) => void;
  api.fetch.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await render();
  const signal = api.fetch.mock.calls[0]![2].signal as AbortSignal;
  expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  expect(container.textContent).not.toContain("Nenhum pedido");
  await render("synthetic-b");
  expect(signal.aborted).toBe(true);
  await act(async () => { resolveOld(Response.json({ ...counts, resumos_ativos: 999 })); });
  expect(container.textContent).not.toContain("999");
});

it("encaminha expiração e ignora erro após desmontar", async () => {
  const error = new SessionExpiredError();
  api.fetch.mockRejectedValueOnce(error);
  await render();
  expect(onSessionError).toHaveBeenCalledWith(error);
  let rejectOld!: (error: unknown) => void;
  api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
  await render("synthetic-b");
  act(() => root.render(null));
  await act(async () => { rejectOld(error); });
  expect(onSessionError).toHaveBeenCalledTimes(1);
});
