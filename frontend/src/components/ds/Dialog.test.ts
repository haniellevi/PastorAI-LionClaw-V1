// @vitest-environment jsdom
/**
 * Gate 7.1 (P2): foco inicial do Dialog da fundação.
 *  - com um alvo marcado [data-autofocus] (ex.: textarea do modal "Mensagem"
 *    do Painel de Hoje), o foco inicial vai para ELE — paridade com o
 *    autoFocus original;
 *  - SEM marcação, o comportamento de todos os demais consumidores é
 *    preservado: foco no primeiro focável do conteúdo;
 *  - Esc fecha (onClose) e o foco retorna ao elemento que abriu.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Dialog } from "./Dialog";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onClose = vi.fn();

function render(open: boolean, children: ReactNode) {
  act(() => {
    root.render(
      h(Dialog, { open, onClose, title: "Teste", description: "desc", children }),
    );
  });
}

function pressEscape() {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
}

beforeEach(() => {
  onClose.mockReset();
  // jsdom não implementa layout: offsetParent (filtro do getFocusable) vira o
  // pai direto — todos os controles contam como visíveis.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("Dialog — foco inicial (Gate 7.1)", () => {
  it("com [data-autofocus] (modal Mensagem): foco inicial vai para o textarea", () => {
    // gatilho com foco antes de abrir
    const opener = document.createElement("button");
    opener.id = "opener";
    document.body.appendChild(opener);
    opener.focus();

    render(
      true,
      h(
        "form",
        null,
        h("textarea", { id: "msg", "data-autofocus": "", key: "t" }),
        h("button", { type: "submit", id: "enviar", key: "b" }, "Enviar"),
      ),
    );

    expect(document.activeElement?.id).toBe("msg");

    // Esc fecha e o foco retorna ao gatilho
    pressEscape();
    expect(onClose).toHaveBeenCalledTimes(1);
    render(false, null); // o pai reage fechando
    expect(document.activeElement?.id).toBe("opener");
    opener.remove();
  });

  it("sem marcação: comportamento original preservado (primeiro focável)", () => {
    render(
      true,
      h(
        "div",
        null,
        h("button", { id: "primeiro", key: "a" }, "A"),
        h("button", { id: "segundo", key: "b" }, "B"),
      ),
    );
    // O primeiro focável do PAINEL é o botão "Fechar" do cabeçalho do Dialog
    // (vem antes do conteúdo no DOM) — exatamente o comportamento pré-7.1.
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Fechar");
  });
});
