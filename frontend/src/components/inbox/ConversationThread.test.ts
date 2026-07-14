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

import type { Conversation } from "@/lib/conversations-api";

import { ConversationThread } from "./ConversationThread";

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

function render(conversation: Conversation) {
  act(() => {
    root.render(
      h(ConversationThread, {
        conversation,
        selfId: "me",
        holderName: null,
        degraded: false,
        busy: false,
        conflict: null,
        messages: [],
        messagesLoading: false,
        panelOpen: false,
        isAdmin: false,
        avatarUrl: null,
        onAssume: () => {},
        onReturn: () => {},
        onSend: () => {},
        onSendMedia: async () => true,
        onTogglePanel: () => {},
        onDelete: () => {},
        onTransfer: () => {},
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
    expect(text).toContain("Assumir (pausar IA)");
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
});
