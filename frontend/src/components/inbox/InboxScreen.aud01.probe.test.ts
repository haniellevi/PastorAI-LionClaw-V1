// @vitest-environment jsdom
/** AUD01 preflight sintético, produto congelado em f7f9db3.
 * Harness adaptado de InboxScreen.race.test.ts: createRoot/act, auth estável,
 * matchMedia desktop e API simulada; InboxScreen e seus filhos são reais.
 * Pausa/retomada externas são snapshots de fetchInboxAgentStatus, sem botão
 * inventado. RED esperado: retry deve finalmente consultar o snapshot atual
 * quando a leitura iniciada antes da pausa ainda está pendente.
 * Não prova alteração de AgentConfig nem execução/backend/envio do agente.
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Conversation, InboxAgentStatus } from "@/lib/conversations-api";

const auth = vi.hoisted(() => ({
  token: "token-sintetico", status: "authenticated",
  user: { roles: ["pastor"], appUserId: "operador-sintetico", churchId: "igreja-sintetica-a" },
  expireSession: vi.fn(),
}));
const api = vi.hoisted(() => ({
  fetchConversations: vi.fn(), fetchInboxAgentStatus: vi.fn(),
  fetchMessages: vi.fn(), fetchConversationPhoto: vi.fn(),
  markConversationRead: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));
vi.mock("@/lib/conversations-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/conversations-api")>(), ...api,
}));
const { InboxScreen } = await import("./InboxScreen");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const active: InboxAgentStatus = { configured: true, ativo: true, pausedByChurch: false };
const paused: InboxAgentStatus = { configured: true, ativo: false, pausedByChurch: true };
const conversation = (id: string): Conversation => ({
  id, nome: `Contato sintético ${id}`, telefone: `55119000000${id.slice(-1)}`, pessoaId: null,
  estado: "ia", ultimaMensagem: "Texto sintético", naoLidas: 0,
  assumidoPor: null, assumidoPorNome: null, assumidoEm: null, esperaDesde: null,
  atualizadoEm: null, tipo: null, semInteresse: false,
});
const page = { items: [conversation("a"), conversation("b")], page: 1, pageSize: 100, total: 2 };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
let container: HTMLDivElement;
let root: Root;
let currentStatus: InboxAgentStatus;
beforeEach(() => {
  vi.useFakeTimers();
  auth.user.churchId = "igreja-sintetica-a";
  currentStatus = active;
  for (const mock of Object.values(api)) mock.mockReset();
  api.fetchConversations.mockResolvedValue(page);
  api.fetchInboxAgentStatus.mockImplementation(async () => currentStatus);
  api.fetchMessages.mockResolvedValue([]);
  api.fetchConversationPhoto.mockResolvedValue(null);
  api.markConversationRead.mockResolvedValue(undefined);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Rede proibida no probe AUD01"); }));
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  expect(globalThis.fetch).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
async function renderInbox() { await act(async () => root.render(h(InboxScreen))); }
async function click(text: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent?.trim() === text);
  expect(button, `Botão real ${text}`).toBeDefined();
  expect(button!.disabled).toBe(false);
  await act(async () => button!.click());
}
function expectPaused() {
  expect(container.textContent).toContain("IA pausada pela igreja");
  expect(container.textContent).toContain("O agente está pausado pela igreja.");
  expect(container.textContent).not.toContain("IA ativa");
  expect(container.textContent).not.toContain("A IA está conduzindo este atendimento automaticamente.");
}
function expectActive() {
  expect(container.textContent).toContain("IA ativa");
  expect(container.textContent).toContain("A IA está conduzindo este atendimento automaticamente.");
}

describe("AUD01 reprodução delimitada no Inbox real", () => {
  it("retry comum observa pausa externa pela nova leitura de status", async () => {
    await renderInbox();
    expectActive();
    currentStatus = paused;
    await click("Atualizar");
    expectPaused();
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
  });

  it("falha da lista e Tentar novamente preservam pausa já lida", async () => {
    currentStatus = paused;
    api.fetchConversations.mockRejectedValueOnce(new Error("falha sintética de lista"));
    await renderInbox();
    expect(container.textContent).toContain("Não foi possível carregar as conversas.");
    await click("Tentar novamente");
    expectPaused();
  });

  it("RED: retry após pausa externa não termina exibindo status ativo antigo", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus.mockImplementationOnce(() => oldStatus.promise);
    api.fetchConversations.mockRejectedValueOnce(new Error("falha sintética de lista"));
    await renderInbox();
    expect(container.textContent).toContain("Não foi possível carregar as conversas.");
    // A leitura inicial capturou active antes da pausa, mas sua entrega atrasou.
    // A próxima consulta devolveria paused. Não há evento de pausa na UI.
    currentStatus = paused;
    await click("Tentar novamente");
    expect(container.textContent).toContain("Estado da IA indisponível");
    await act(async () => oldStatus.resolve(active));
    // Oráculo de frescor: o retry solicitado após a pausa deve obter a leitura
    // atual, por cancelamento/substituição ou consulta subsequente ao voo antigo.
    // Sem avançar até o próximo polling: este caso verifica o retry comum.
    expectPaused();
  });

  it("lista tardia após retry não apaga pausa confirmada", async () => {
    await renderInbox();
    const list = deferred<typeof page>();
    api.fetchConversations.mockImplementationOnce(() => list.promise);
    currentStatus = paused;
    await click("Atualizar");
    expectPaused();
    await act(async () => list.resolve(page));
    expectPaused();
  });

  it("erro de status no retry não presume atividade", async () => {
    currentStatus = paused;
    await renderInbox();
    expectPaused();
    api.fetchInboxAgentStatus.mockRejectedValueOnce(new Error("falha sintética de status"));
    await click("Atualizar");
    expect(container.textContent).toContain("Estado da IA indisponível");
    expect(container.textContent).not.toContain("IA ativa");
  });

  it("troca de igreja rejeita status ativo tardio da igreja anterior", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus.mockImplementationOnce(() => oldStatus.promise);
    await renderInbox();
    const oldSignal = api.fetchInboxAgentStatus.mock.calls[0]![1] as AbortSignal;
    currentStatus = paused;
    auth.user.churchId = "igreja-sintetica-b";
    await renderInbox();
    expect(oldSignal.aborted).toBe(true);
    expectPaused();
    await act(async () => oldStatus.resolve(active));
    expectPaused();
  });

  it("troca de conversa durante lista pendente mantém pausa global", async () => {
    currentStatus = paused;
    await renderInbox();
    const list = deferred<typeof page>();
    api.fetchConversations.mockImplementationOnce(() => list.promise);
    await click("Atualizar");
    const button = [...container.querySelectorAll<HTMLButtonElement>("button.conv")]
      .find((item) => item.textContent?.includes("Contato sintético b"));
    expect(button).toBeDefined();
    await act(async () => button!.click());
    await act(async () => list.resolve(page));
    expect(container.querySelector(".thread-head")?.textContent).toContain("Contato sintético b");
    expectPaused();
  });

  it("retomada humana externa legítima aparece somente pela leitura nova", async () => {
    currentStatus = paused;
    await renderInbox();
    expectPaused();
    currentStatus = active; // Hipótese: operador retomou fora do Inbox.
    expectPaused();
    await click("Atualizar");
    expectActive();
  });

  it("controle positivo mantém IA ativa no retry sem pausa", async () => {
    await renderInbox();
    await click("Atualizar");
    expectActive();
    expect(api.fetchConversations).toHaveBeenCalledTimes(2);
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
  });
});


// Regressões adicionais do candidato; os nove casos originais permanecem intactos.
describe("AUD01 frescor e ciclo de vida da consulta posterior", () => {
  it("coalesce retries e fica unknown até a nova leitura terminar", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    const newStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus
      .mockImplementationOnce(() => oldStatus.promise)
      .mockImplementationOnce(() => newStatus.promise);
    await renderInbox();
    await click("Atualizar");
    await click("Atualizar");
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    await act(async () => oldStatus.resolve(active));
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Estado da IA indisponível");
    expect(container.textContent).not.toContain("IA ativa");
    // Polling continua single-flight enquanto a leitura posterior está em voo.
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
    await act(async () => newStatus.resolve(paused));
    expectPaused();
  });

  it("falha da nova leitura conserva unknown apesar do active antigo", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus
      .mockImplementationOnce(() => oldStatus.promise)
      .mockRejectedValueOnce(new Error("falha sintética da leitura posterior"));
    await renderInbox();
    await click("Atualizar");
    await act(async () => oldStatus.resolve(active));
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Estado da IA indisponível");
    expect(container.textContent).not.toContain("IA ativa");
  });

  it("timeout do voo antigo libera leitura posterior e ignora sucesso tardio", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus.mockImplementationOnce(() => oldStatus.promise);
    await renderInbox();
    currentStatus = paused;
    await click("Atualizar");
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
    expect((api.fetchInboxAgentStatus.mock.calls[0]![1] as AbortSignal).aborted).toBe(true);
    expectPaused();
    await act(async () => oldStatus.resolve(active));
    expectPaused();
  });

  it("troca de igreja descarta também a intenção de retry do escopo antigo", async () => {
    const oldStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus.mockImplementationOnce(() => oldStatus.promise);
    await renderInbox();
    await click("Atualizar");
    currentStatus = paused;
    auth.user.churchId = "igreja-sintetica-b";
    await renderInbox();
    expectPaused();
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
    await act(async () => oldStatus.resolve(active));
    expectPaused();
    expect(api.fetchInboxAgentStatus).toHaveBeenCalledTimes(2);
  });

  it("retry invalida active conhecido enquanto a nova leitura está pendente", async () => {
    await renderInbox();
    expectActive();
    const newStatus = deferred<InboxAgentStatus>();
    api.fetchInboxAgentStatus.mockImplementationOnce(() => newStatus.promise);
    await click("Atualizar");
    expect(container.textContent).toContain("Estado da IA indisponível");
    expect(container.textContent).not.toContain("IA ativa");
    await act(async () => newStatus.resolve(paused));
    expectPaused();
  });
});
