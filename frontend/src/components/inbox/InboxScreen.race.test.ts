// @vitest-environment jsdom
/**
 * INBOX-RACE-1 — a resposta de GET /conversations/{id}/messages de uma conversa
 * ANTIGA não pode sobrescrever a thread da conversa atual.
 *
 * O inbox dispara `fetchMessages` a cada troca de conversa (e também no polling
 * e após enviar). Sem guarda, uma resposta lenta de A que chega depois de o
 * usuário abrir B aparecia sob o cabeçalho de B — e o `finally` dela ainda
 * apagava o "Carregando conversa…" de B antes da hora.
 *
 * As promessas de cada conversa são controladas na mão (nada resolve sozinho),
 * para provar exatamente a ordem A-começa → B-começa → B-resolve → A-resolve.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage, Conversation } from "@/lib/conversations-api";

// Objeto ESTÁVEL entre renders: o inbox memoiza `loadMessages` a partir de
// `expireSession`; devolver uma referência nova a cada render invalidaria o
// useCallback e o efeito de troca de conversa entraria em laço infinito.
const auth = vi.hoisted(() => ({
  token: "tok-1",
  // pastor: acessa o inbox, não é admin e não lê a conexão do WhatsApp
  // (canManageWhatsapp) — mantém o teste no caminho de mensagens.
  user: { roles: ["pastor"] as string[], appUserId: "u-1" },
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));

const apiMock = vi.hoisted(() => ({
  fetchConversations: vi.fn(),
  fetchMessages: vi.fn(),
  fetchConversationPhoto: vi.fn(),
}));

vi.mock("@/lib/conversations-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/conversations-api")>();
  return {
    ...actual,
    fetchConversations: apiMock.fetchConversations,
    fetchMessages: apiMock.fetchMessages,
    fetchConversationPhoto: apiMock.fetchConversationPhoto,
  };
});

const { InboxScreen } = await import("./InboxScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---- fixtures --------------------------------------------------------------
const conv = (id: string, nome: string): Conversation => ({
  id,
  telefone: `55119000000${id.slice(-1)}`,
  pessoaId: null,
  nome,
  estado: "ia",
  ultimaMensagem: "Bom dia!",
  naoLidas: 0,
  assumidoPor: null,
  assumidoPorNome: null,
  assumidoEm: null,
  esperaDesde: null,
  atualizadoEm: null,
  tipo: null,
  semInteresse: false,
});

const msg = (id: string, texto: string): ChatMessage => ({
  id,
  direcao: "in",
  autor: "contato",
  autorNome: null,
  tipo: "texto",
  texto,
  mediaUrl: null,
  mediaMime: null,
  mediaNome: null,
  criadoEm: "2026-07-30T12:00:00Z",
});

const CONV_A = conv("conv-a", "Ana Souza");
const CONV_B = conv("conv-b", "Bruno Lima");
const MSGS_A = [msg("m-a1", "mensagem antiga da Ana")];
const MSGS_B = [msg("m-b1", "mensagem atual do Bruno")];

// ---- promessas controladas -------------------------------------------------
/** Requisições de mensagens em voo, na ordem em que foram disparadas. */
let pending: Array<{ convId: string; resolve: (items: ChatMessage[]) => void }>;

/** Resolve TODAS as requisições em voo daquela conversa. */
async function resolveMessages(convId: string, items: ChatMessage[]) {
  const alvos = pending.filter((p) => p.convId === convId);
  if (alvos.length === 0) throw new Error(`nenhuma requisição em voo para ${convId}`);
  pending = pending.filter((p) => p.convId !== convId);
  await act(async () => {
    alvos.forEach((p) => p.resolve(items));
  });
}

// ---- harness ---------------------------------------------------------------
let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  pending = [];

  // jsdom não implementa matchMedia; o inbox usa para o master-detail mobile.
  // matches=false ⇒ desktop (lista + thread lado a lado, seleção automática).
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));

  apiMock.fetchConversations.mockReset();
  apiMock.fetchConversations.mockResolvedValue({
    items: [CONV_A, CONV_B],
    page: 1,
    pageSize: 100,
    total: 2,
  });
  apiMock.fetchConversationPhoto.mockReset();
  apiMock.fetchConversationPhoto.mockResolvedValue(null);
  apiMock.fetchMessages.mockReset();
  apiMock.fetchMessages.mockImplementation(
    (_token: string, convId: string) =>
      new Promise<ChatMessage[]>((resolve) => {
        pending.push({ convId, resolve });
      }),
  );

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

/** Renderiza o inbox; no desktop a 1ª conversa (A) já abre sozinha. */
async function renderInbox() {
  await act(async () => {
    root.render(h(InboxScreen, {}));
  });
}

function threadBody(): HTMLElement {
  const el = container.querySelector<HTMLElement>(".thread-body");
  if (!el) throw new Error("thread-body não encontrada");
  return el;
}

function convButton(nome: string): HTMLElement {
  const btn = [...container.querySelectorAll<HTMLElement>("button.conv")].find((b) =>
    (b.textContent ?? "").includes(nome),
  );
  if (!btn) throw new Error(`conversa "${nome}" não encontrada na lista`);
  return btn;
}

function selectConversation(nome: string) {
  act(() => {
    convButton(nome).dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("InboxScreen — resposta obsoleta não sobrescreve a conversa atual (INBOX-RACE-1)", () => {
  it("A começa, B começa, B resolve, A resolve depois: a thread mostra só as mensagens de B", async () => {
    // 1) conversa A selecionada (seleção automática do desktop)…
    await renderInbox();
    expect(container.querySelector("button.conv[aria-current='true']")?.textContent).toContain(
      "Ana Souza",
    );
    // 2) …com a requisição de A em voo.
    expect(pending.map((p) => p.convId)).toEqual(["conv-a"]);

    // 3) usuário troca para a conversa B…
    selectConversation("Bruno Lima");
    expect(container.querySelector("button.conv[aria-current='true']")?.textContent).toContain(
      "Bruno Lima",
    );
    // 4) …disparando a requisição de B, com a de A ainda em voo.
    expect(pending.map((p) => p.convId)).toEqual(["conv-a", "conv-b"]);

    // 5) B responde primeiro: a thread passa a mostrar as mensagens de B.
    await resolveMessages("conv-b", MSGS_B);
    expect(threadBody().textContent).toContain("mensagem atual do Bruno");

    // 6) A (obsoleta) responde DEPOIS.
    await resolveMessages("conv-a", MSGS_A);

    // 7) a UI continua sendo só a de B — nada da Ana vazou para o cabeçalho do Bruno.
    expect(threadBody().textContent).not.toContain("mensagem antiga da Ana");
    expect(threadBody().textContent).toContain("mensagem atual do Bruno");
    expect(threadBody().querySelectorAll(".msg").length).toBe(1);
    expect(container.querySelector("button.conv[aria-current='true']")?.textContent).toContain(
      "Bruno Lima",
    );
  });

  it("a resposta obsoleta de A não encerra o 'carregando' da conversa B", async () => {
    await renderInbox();
    selectConversation("Bruno Lima");
    expect(pending.map((p) => p.convId)).toEqual(["conv-a", "conv-b"]);

    // A (obsoleta) responde enquanto B ainda está em voo: o skeleton de B fica.
    await resolveMessages("conv-a", MSGS_A);
    expect(threadBody().textContent).toContain("Carregando conversa…");
    expect(threadBody().textContent).not.toContain("Ainda não há mensagens nesta conversa.");
    expect(threadBody().textContent).not.toContain("mensagem antiga da Ana");

    // Só a resposta de B encerra o carregamento e preenche a thread.
    await resolveMessages("conv-b", MSGS_B);
    expect(threadBody().textContent).not.toContain("Carregando conversa…");
    expect(threadBody().textContent).toContain("mensagem atual do Bruno");
  });

  it("voltar para A depois exibe as mensagens de A (a guarda não trava a thread)", async () => {
    await renderInbox();
    selectConversation("Bruno Lima");
    await resolveMessages("conv-b", MSGS_B);
    await resolveMessages("conv-a", MSGS_A);

    selectConversation("Ana Souza");
    expect(pending.map((p) => p.convId)).toEqual(["conv-a"]);
    await resolveMessages("conv-a", MSGS_A);

    expect(threadBody().textContent).toContain("mensagem antiga da Ana");
    expect(threadBody().textContent).not.toContain("mensagem atual do Bruno");
  });
});
