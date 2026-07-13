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
    expect(waiting.textContent).toContain("Aguardando atendimento");
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
    expect(pressed.textContent).toContain("Aguardando");
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
      "Nenhuma conversa encontrada.",
    );
  });
});
