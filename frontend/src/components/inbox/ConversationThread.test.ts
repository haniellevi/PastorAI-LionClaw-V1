// @vitest-environment jsdom
/**
 * CONV-AI-1: a thread do inbox nunca exibe "IA ativa" + ação enganosa de
 * "Assumir (pausar IA)" para um contato "sem interesse" — a IA já está suspensa
 * no backend. O fluxo normal (contato comum) permanece exatamente igual.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { ChatMessage, Conversation } from "@/lib/conversations-api";

import { ConversationThread } from "./ConversationThread";
import type { AgentAvailability } from "./conversation-format";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const conv = (over: Partial<Conversation>): Conversation => ({
  id: "c1",
  telefone: "5511987654321",
  pessoaId: "p1",
  nome: "Ana Souza",
  estado: "ia",
  ultimaMensagem: "Bom dia!",
  naoLidas: 0,
  assumidoPor: null,
  assumidoPorNome: null,
  assumidoEm: null,
  esperaDesde: null,
  atualizadoEm: null,
  tipo: "contato",
  semInteresse: false,
  ...over,
});

let container: HTMLDivElement;
let root: Root;

function render(
  conversation: Conversation,
  agentAvailability: AgentAvailability = "active",
  messages: ChatMessage[] = [],
  overrides: Partial<Parameters<typeof ConversationThread>[0]> = {},
) {
  act(() => {
    root.render(
      h(ConversationThread, {
        conversation,
        selfId: "me",
        recordingContext: {},
        holderName: null,
        degraded: false,
        agentAvailability,
        busy: false,
        conflict: null,
        messages,
        messagesLoading: false,
        panelOpen: false,
        isAdmin: false,
        avatarUrl: null,
        onAssume: () => {},
        onReturn: () => {},
        onSend: async () => true,
        draft: "",
        sendingText: false,
        onDraftChange: () => {},
        onSendMedia: async () => true,
        onTogglePanel: () => {},
        onDelete: () => {},
        onTransfer: () => {},
        ...overrides,
      }),
    );
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ConversationThread — sem interesse ⇒ IA pausada (CONV-AI-1)", () => {
  it("contato normal (estado ia): 'IA ativa' + 'Assumir (pausar IA)'", () => {
    render(conv({ semInteresse: false, estado: "ia" }));
    const text = container.textContent ?? "";
    expect(text).toContain("IA ativa");
    expect(text).toContain("Assumir atendimento");
    expect(text).toContain("conduzindo este atendimento automaticamente");
  });

  it("sem interesse: 'IA pausada', 'Assumir atendimento' e sem 'pausar IA'", () => {
    render(conv({ semInteresse: true, estado: "ia" }));
    const text = container.textContent ?? "";
    expect(text).toContain("IA pausada");
    expect(text).not.toContain("IA ativa");
    // Ação NÃO enganosa: não promete "pausar IA" (não há IA ativa para pausar).
    expect(text).toContain("Assumir atendimento");
    expect(text).not.toContain("pausar IA");
    expect(text).toContain("pausada para este contato");
    // A ação de assumir continua disponível (humano ainda pode responder).
    const assume = container.querySelector('[aria-label="Assumir atendimento"]');
    expect(assume).not.toBeNull();
  });

  it("sem interesse sob meu atendimento: 'Encerrar atendimento', nunca 'Devolver para a IA'", () => {
    // Humano assumiu um contato sem interesse: o release NÃO promete devolver
    // para uma IA que o backend mantém suprimida (espelha o fix do 'Assumir').
    render(conv({ semInteresse: true, estado: "humano", assumidoPor: "me" }));
    const text = container.textContent ?? "";
    expect(text).toContain("Encerrar atendimento");
    expect(text).not.toContain("Devolver para a IA");
    expect(container.querySelector('[aria-label="Encerrar atendimento"]')).not.toBeNull();
  });

  it("contato normal sob meu atendimento mantém 'Devolver para a IA'", () => {
    render(conv({ semInteresse: false, estado: "humano", assumidoPor: "me" }));
    const text = container.textContent ?? "";
    expect(text).toContain("Devolver para a IA");
    expect(text).not.toContain("Encerrar atendimento");
  });

  it("sem interesse sob OUTRO líder: botão desabilitado usa 'Assumir atendimento', nunca 'pausar IA'", () => {
    // Held-by-other: o botão fica DESABILITADO (não muda handoff/permissão), mas
    // o rótulo não pode prometer "pausar IA" — a IA já está suprimida no backend.
    render(conv({ semInteresse: true, estado: "humano", assumidoPor: "outro-lider" }));
    const text = container.textContent ?? "";
    expect(text).toContain("Assumir atendimento");
    expect(text).not.toContain("pausar IA");
    const assume = container.querySelector('[aria-label="Assumir atendimento"]');
    expect(assume).not.toBeNull();
    expect((assume as HTMLButtonElement).disabled).toBe(true);
  });

  it("agente global inativo mostra 'IA pausada pela igreja' e não promete pausar novamente", () => {
    render(conv({ semInteresse: false, estado: "ia" }), "paused_by_church");
    const text = container.textContent ?? "";
    expect(text).toContain("IA pausada pela igreja");
    expect(text).not.toContain("IA ativa");
    expect(text).toContain("O agente está pausado pela igreja");
    expect(text).toContain("Assumir atendimento");
    expect(text).not.toContain("Assumir (pausar IA)");
  });

  it("atendimento humano não oferece devolução para agente global inativo", () => {
    render(
      conv({ semInteresse: false, estado: "humano", assumidoPor: "me" }),
      "paused_by_church",
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Encerrar atendimento");
    expect(text).not.toContain("Devolver para a IA");
  });

  it("estado global desconhecido não exibe 'IA ativa'", () => {
    render(conv({ semInteresse: false, estado: "ia" }), "unknown");
    const text = container.textContent ?? "";
    expect(text).toContain("Estado da IA indisponível");
    expect(text).not.toContain("IA ativa");
    expect(text).toContain("Assumir atendimento");
  });
});


it("renders the server pastoral marker as text without media controls", () => {
  render(conv({ ultimaMensagem: "Mensagem pastoral protegida" }), "active", [{
    id: "private-synthetic", direcao: "in", autor: "contato", autorNome: null,
    tipo: "texto", texto: "Mensagem pastoral protegida",
    mediaUrl: null, mediaMime: null, mediaNome: null, criadoEm: "2026-10-18T12:00:00Z",
  }]);
  expect(container.querySelector('[role="note"][aria-label="Mensagem pastoral protegida"]')).not.toBeNull();
  expect(container.textContent).toContain("Encaminhe o atendimento ao pastor.");
  expect(container.querySelector(".msg-img, audio, a[download]")).toBeNull();
});

it("exibe conteúdo entregue pelo servidor sem inferir leitura pelo papel", () => {
  render(conv({}), "active", [{
    id: "authorized", direcao: "in", autor: "contato", autorNome: null,
    tipo: "texto", texto: "Oração sintética autorizada", mediaUrl: null,
    mediaMime: null, mediaNome: null, criadoEm: "2026-10-18T12:00:00Z",
  }]);
  expect(container.textContent).toContain("Oração sintética autorizada");
  expect(container.textContent).not.toContain("Encaminhe o atendimento ao pastor.");
});

it("foca o cabeçalho só ao abrir/trocar e anuncia novas entradas sem reler histórico", () => {
  const message = (id: string): ChatMessage => ({
    id, direcao: "in", autor: "contato", autorNome: null, tipo: "texto",
    texto: "Texto sintético", mediaUrl: null, mediaMime: null, mediaNome: null,
    criadoEm: "2026-10-20T12:00:00Z",
  });
  render(conv({}), "active", [message("one")]);
  expect(document.activeElement).toBe(container.querySelector("h2"));
  const status = () => container.querySelector('.thread-head [role="status"]')?.textContent;
  expect(status()).toBe("");
  const history = container.querySelector<HTMLElement>('[aria-label="Histórico da conversa"]')!;
  history.focus();
  render(conv({}), "active", [message("older"), message("one")]);
  expect(status()).toBe("");
  expect(document.activeElement).toBe(history);
  render(conv({}), "active", [message("older"), message("one"), message("two")]);
  expect(status()).toBe("1 nova mensagem recebida.");
  expect(document.activeElement).toBe(history);
  render(conv({}), "active", [message("older"), message("one"), message("two")]);
  expect(status()).toBe("1 nova mensagem recebida.");
  render(conv({ id: "c2" }), "active", [message("other")]);
  expect(status()).toBe("");
  expect(document.activeElement).toBe(container.querySelector("h2"));
});


it("anuncia a primeira entrada numa conversa vazia e repete avisos iguais só para IDs novos", () => {
  const message: ChatMessage = {
    id: "new-one", direcao: "in", autor: "contato", autorNome: null, tipo: "texto",
    texto: "Texto sintético", mediaUrl: null, mediaMime: null, mediaNome: null,
    criadoEm: "2026-10-20T12:00:00Z",
  };
  render(conv({}));
  render(conv({}), "active", [message]);
  const status = container.querySelector('.thread-head [role="status"]')!;
  expect(status.textContent).toBe("1 nova mensagem recebida.");
  const first = status.firstChild;
  render(conv({}), "active", [message, { ...message, id: "new-two" }]);
  expect(status.textContent).toBe("1 nova mensagem recebida.");
  expect(status.firstChild).not.toBe(first);
  const second = status.firstChild;
  render(conv({}), "active", [message, { ...message, id: "new-two" }]);
  expect(status.firstChild).toBe(second);
});

it.each([true, false])("anuncia envio e resultado sem conteúdo privado (sucesso=%s)", async (ok) => {
  let finish!: (result: boolean) => void;
  const pending = new Promise<boolean>((resolve) => { finish = resolve; });
  render(conv({ estado: "humano", assumidoPor: "me" }), "active", [], {
    draft: "Resposta sintética", onSend: () => pending,
  });
  act(() => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  const status = container.querySelector('.thread-head [role="status"]')!;
  expect(status.textContent).toBe("Enviando mensagem…");
  await act(async () => finish(ok));
  expect(status.textContent).toBe(ok ? "Mensagem enviada." : "Não foi possível enviar a mensagem. Tente novamente.");
  expect(status.textContent).not.toContain("Resposta sintética");
});
