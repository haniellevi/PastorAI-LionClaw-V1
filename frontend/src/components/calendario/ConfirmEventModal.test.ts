// @vitest-environment jsdom
/**
 * Wave Visual W3 — migração do ConfirmEventModal para o DsDialog (Gate 5).
 *  - título "Confirmar evento";
 *  - Esc fecha (onClose) quando não está ocupado, e é bloqueado por `busy`
 *    (mesma trava dos demais diálogos já migrados).
 *
 * "Notificar sobre este evento" começa desmarcado — `fetchConversations` só é
 * chamado quando o toggle liga (efeito condicionado a `notify`), então este
 * teste de foco/Esc não precisa mockar a API de conversas.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/lib/events-api";

import { ConfirmEventModal } from "./ConfirmEventModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const event: EventItem = {
  id: "ev-1",
  titulo: "Culto de domingo",
  data: "2026-07-19",
  hora: "18:00",
  descricao: null,
  googleEventId: null,
  sincronizado: false,
  status: "a_confirmar",
};

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;
const onClose = vi.fn();
const onSubmit = vi.fn();

function render(busy: boolean) {
  act(() => {
    root.render(
      h(ConfirmEventModal, {
        event,
        token: "tok-1",
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
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  opener = document.createElement("button");
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

describe("ConfirmEventModal — migração DsDialog", () => {
  it("título 'Confirmar evento'", () => {
    render(false);
    expect(container.querySelector("h2")?.textContent).toBe("Confirmar evento");
  });

  it("Esc fecha (onClose) quando não está ocupado", () => {
    render(false);
    pressEscape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc NÃO fecha enquanto busy=true", () => {
    render(true);
    pressEscape();
    expect(onClose).not.toHaveBeenCalled();
  });
});
