// @vitest-environment jsdom
/**
 * Gate 8 (Onda 4B): regressão da lista de conversas — a repaginação visual não
 * pode perder informação nem acessibilidade:
 *  - "aguardando" é comunicado por TEXTO (nunca só cor);
 *  - filtros com aria-pressed e callbacks intactos;
 *  - seleção marca aria-current e a linha certa;
 *  - não lidas com aria-label; nome/trecho/horário presentes.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/conversations-api";

import { ConversationList, type ConvFilter } from "./ConversationList";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-07-13T15:00:00Z");

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
  atualizadoEm: new Date(NOW - 5 * 60e3).toISOString(),
  tipo: "visitante",
  semInteresse: false,
  ...over,
});

let container: HTMLDivElement;
let root: Root;

function render(props: Partial<Parameters<typeof ConversationList>[0]> = {}) {
  act(() => {
    root.render(
      h(ConversationList, {
        conversations: [
          conv({ id: "c1", nome: "Ana Souza", naoLidas: 2 }),
          conv({
            id: "c2",
            nome: "Marcos Lima",
            estado: "aguardando",
            esperaDesde: new Date(NOW - 18 * 60e3).toISOString(),
          }),
        ],
        selectedId: "c1",
        filter: "todas" as ConvFilter,
        waitingCount: 1,
        now: NOW,
        search: "",
        onSelect: () => {},
        onFilter: () => {},
        onSearch: () => {},
        ...props,
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

describe("ConversationList — Gate 8", () => {
  it("aguardando é comunicado por TEXTO (ícone+texto, nunca só cor)", () => {
    render();
    const rows = [...container.querySelectorAll(".conv")];
    const waiting = rows.find((r) => r.textContent!.includes("Marcos Lima"))!;
    expect(waiting.textContent).toContain("Em espera");
    const other = rows.find((r) => r.textContent!.includes("Ana Souza"))!;
    expect(other.textContent).not.toContain("Aguardando atendimento");
  });

  it("seleção marca aria-current na linha certa; badge de não lidas nomeada", () => {
    render();
    const active = container.querySelector('.conv[aria-current="true"]')!;
    expect(active.textContent).toContain("Ana Souza");
    expect(container.querySelector('[aria-label="2 não lidas"]')).not.toBeNull();
  });

  it("filtros: aria-pressed reflete o ativo e o clique dispara onFilter", () => {
    const onFilter = vi.fn();
    render({ filter: "aguardando", onFilter });
    const pressed = container.querySelector('.ib-filter-btn[aria-pressed="true"]')!;
    expect(pressed.textContent).toContain("Em espera");
    expect(pressed.textContent).toContain("1"); // contador real
    act(() => {
      [...container.querySelectorAll(".ib-filter-btn")]
        .find((b) => b.textContent!.trim() === "IA")!
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onFilter).toHaveBeenCalledWith("ia");
  });

  it("clique na linha dispara onSelect com o id; busca dispara onSearch", () => {
    const onSelect = vi.fn();
    render({ onSelect });
    act(() => {
      [...container.querySelectorAll(".conv")]
        .find((r) => r.textContent!.includes("Marcos Lima"))!
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onSelect).toHaveBeenCalledWith("c2");
    expect(container.querySelector('input[type="search"]')).not.toBeNull();
  });

  it("lista vazia mostra o estado vazio da fundação", () => {
    render({ conversations: [] });
    expect(container.querySelector(".ds-empty-title")?.textContent).toContain(
      "Ainda não há conversas.",
    );
  });

  it("responsável próprio fica explícito mesmo antes de carregar o nome", () => {
    render({ selfId: "eu", conversations: [conv({ estado: "humano", assumidoPor: "eu", assumidoPorNome: null })] });
    expect(container.textContent).toContain("Em atendimento por você");
  });

  it("estado humano sem nome nunca inventa um responsável", () => {
    render({ conversations: [conv({ estado: "humano", assumidoPor: "outro", assumidoPorNome: null })] });
    expect(container.textContent).toContain("Responsável não informado");
  });

  it("última página anuncia a conclusão e conserva um destino de teclado", () => {
    render({ partialList: true, loadedCount: 100, total: 103, hasMore: true, onLoadMore: () => {} });
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('Carregar mais conversas'))!;
    button.focus();
    act(() => button.click());
    render({ partialList: true, loadedCount: 100, total: 103, hasMore: true, loadingMore: true, onLoadMore: () => {} });
    render({ loadedCount: 103, total: 103, hasMore: false });
    expect(document.activeElement).toBe(container.querySelector('input[type="search"]'));
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Todas as 103 conversas foram carregadas.');
  });

  it("conclusão da página não rouba foco de quem mudou para outro campo", () => {
    const composer = document.createElement('input');
    document.body.appendChild(composer);
    try {
      render({ hasMore: true, onLoadMore: () => {} });
      const button = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('Carregar mais conversas'))!;
      button.focus();
      act(() => button.click());
      render({ hasMore: true, loadingMore: true, onLoadMore: () => {} });
      composer.focus();
      render({ loadedCount: 103, total: 103, hasMore: false });
      expect(document.activeElement).toBe(composer);
    } finally {
      composer.remove();
    }
  });
});
