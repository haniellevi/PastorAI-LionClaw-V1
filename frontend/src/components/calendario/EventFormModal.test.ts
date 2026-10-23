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
import type { EventItem } from "@/lib/events-api";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;
let unmounted = false;
const onClose = vi.fn();
const onSubmit = vi.fn();

function render(busy: boolean, event?: EventItem) {
  act(() => {
    root.render(
      h(EventFormModal, {
        event,
        busy,
        error: null,
        onClose,
        onSubmit,
      }),
    );
  });
}

function setValue(element: HTMLInputElement | HTMLSelectElement, value: string) {
  const prototype = element instanceof HTMLSelectElement
    ? HTMLSelectElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  act(() => {
    setter?.call(element, value);
    element.dispatchEvent(
      new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }),
    );
  });
}

function submitForm() {
  act(() => {
    container.querySelector("form")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
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
  unmounted = false;
});

afterEach(() => {
  if (!unmounted) act(() => root.unmount());
  container.remove();
  opener.remove();
});

describe("EventFormModal — migração DsDialog", () => {
  it("abre em modo criação, título 'Novo evento', foco inicial no campo Título", () => {
    render(false);
    expect(container.querySelector("h2")?.textContent).toBe("Novo evento");
    const active = document.activeElement as HTMLInputElement;
    expect(active.getAttribute("data-autofocus")).toBe("");
    // API semântica (HTMLInputElement.labels), não adjacência de DOM.
    expect(active.labels?.length).toBe(1);
    expect(active.labels?.[0]?.textContent).toBe("Título");
  });

  it("Esc fecha (onClose) e o foco retorna ao elemento que abriu o modal", () => {
    render(false);
    pressEscape();
    expect(onClose).toHaveBeenCalledTimes(1);
    // onClose real (fora deste teste isolado) desmontaria o EventFormModal —
    // simula essa reação do pai pra provar o retorno de foco do primitive.
    act(() => root.unmount());
    unmounted = true;
    expect(document.activeElement).toBe(opener);
  });

  it("Esc NÃO fecha enquanto está salvando (busy=true)", () => {
    render(true);
    pressEscape();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("salva uma janela permitida e públicos existentes com rótulos acessíveis", () => {
    render(false);
    const title = [...container.querySelectorAll<HTMLInputElement>("input")].find(
      (input) => input.labels?.[0]?.textContent === "Título",
    );
    const date = container.querySelector<HTMLInputElement>('input[type="date"]');
    const window = container.querySelector<HTMLSelectElement>('select[id$="-reminder-window"]');
    const cellLeaders = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
      .find((input) => input.labels?.[0]?.textContent?.includes("Líderes de célula"));

    expect(window?.labels?.[0]?.textContent).toBe("Janela do lembrete");
    expect(cellLeaders?.labels?.length).toBe(1);
    expect(cellLeaders?.closest("fieldset")?.querySelector("legend")?.textContent)
      .toBe("Público elegível para o lembrete");

    if (!title || !date || !window || !cellLeaders) throw new Error("Campos do formulário ausentes");
    setValue(title, "Encontro da igreja");
    setValue(date, "2026-11-01");
    setValue(window, "24");
    act(() => cellLeaders.click());
    submitForm();

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      titulo: "Encontro da igreja",
      data: "2026-11-01",
      antecedenciaHoras: 24,
      publicoAlvo: ["lideres_celula"],
    }));
  });

  it("associa o erro de público ao grupo quando há janela sem público", () => {
    render(false);
    const title = [...container.querySelectorAll<HTMLInputElement>("input")].find(
      (input) => input.labels?.[0]?.textContent === "Título",
    );
    const date = container.querySelector<HTMLInputElement>('input[type="date"]');
    const window = container.querySelector<HTMLSelectElement>('select[id$="-reminder-window"]');
    if (!title || !date || !window) throw new Error("Campos do formulário ausentes");

    setValue(title, "Encontro da igreja");
    setValue(date, "2026-11-01");
    setValue(window, "2");
    submitForm();

    const fieldset = container.querySelector("fieldset");
    const error = container.querySelector("#" + fieldset?.getAttribute("aria-describedby"));
    expect(error?.textContent).toContain("Selecione ao menos um público");
    expect(error?.getAttribute("role")).toBe("alert");
    expect(container.querySelector('input[type="checkbox"]')?.getAttribute("aria-invalid"))
      .toBe("true");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
