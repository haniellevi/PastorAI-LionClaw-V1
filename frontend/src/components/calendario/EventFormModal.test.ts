// @vitest-environment jsdom
/**
 * Wave Visual W3 — migração do EventFormModal para o DsDialog (Gate 5).
 *  - foco inicial vai para o campo "Título" (data-autofocus substitui o
 *    autoFocus nativo — preferido pelo primitive sobre o primeiro focável
 *    padrão, que seria o botão "Fechar" do cabeçalho);
 *  - Esc fecha (onClose) quando não está salvando, e o foco retorna ao
 *    elemento que abriu o modal;
 *  - Esc NÃO fecha enquanto `busy` (salvando) — mesma trava dos demais
 *    diálogos já migrados (Gate 8/9).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EventFormModal } from "./EventFormModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;
const onClose = vi.fn();
const onSubmit = vi.fn();

function render(busy: boolean) {
  act(() => {
    root.render(
      h(EventFormModal, {
        busy,
        error: null,
        onClose,
        onSubmit,
      }),
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
  onSubmit.mockReset();
  // jsdom não implementa layout: offsetParent (filtro do getFocusable) vira o
  // pai direto — todos os controles contam como visíveis.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  opener = document.createElement("button");
  opener.id = "opener";
  document.body.appendChild(opener);
  opener.focus();

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  opener.remove();
});

describe("EventFormModal — migração DsDialog", () => {
  it("abre em modo criação, título 'Novo evento', foco inicial no campo Título", () => {
    render(false);
    expect(container.querySelector("h2")?.textContent).toBe("Novo evento");
    expect(document.activeElement?.getAttribute("data-autofocus")).toBe("");
    expect((document.activeElement as HTMLInputElement)?.previousElementSibling?.textContent).toBe(
      "Título",
    );
  });

  it("Esc fecha (onClose) quando não está salvando, e o foco volta ao gatilho", () => {
    render(false);
    pressEscape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc NÃO fecha enquanto está salvando (busy=true)", () => {
    render(true);
    pressEscape();
    expect(onClose).not.toHaveBeenCalled();
  });
});
