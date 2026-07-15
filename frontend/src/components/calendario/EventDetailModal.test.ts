// @vitest-environment jsdom
/**
 * Wave Visual W3 — migração do EventDetailModal para o DsDialog (Gate 5).
 *  - título do diálogo é o próprio nome do evento (antes o aria-label dizia
 *    "Detalhe do evento X" enquanto o texto visível só mostrava "X" —
 *    divergência corrigida pela migração: agora há uma única fonte, o `title`);
 *  - `canManage=false` não renderiza rodapé de ações (nem um `<footer>` vazio);
 *  - `canManage=true` mostra as ações no rodapé do primitive;
 *  - Esc fecha (onClose) quando não está ocupado, e é bloqueado por `busy`
 *    (mesma trava dos demais diálogos já migrados).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/lib/events-api";

import { EventDetailModal } from "./EventDetailModal";

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
  sincronizado: true,
};

let container: HTMLDivElement;
let root: Root;
let opener: HTMLButtonElement;
const onClose = vi.fn();
const onEdit = vi.fn();
const onDelete = vi.fn();
const onConfirm = vi.fn();

function render(canManage: boolean, busy = false) {
  act(() => {
    root.render(
      h(EventDetailModal, {
        event,
        canManage,
        busy,
        error: null,
        onClose,
        onEdit,
        onDelete,
        onConfirm,
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
  onEdit.mockReset();
  onDelete.mockReset();
  onConfirm.mockReset();
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

describe("EventDetailModal — migração DsDialog", () => {
  it("título do diálogo é o nome do evento (fonte única, sem divergência de aria-label)", () => {
    render(true);
    expect(container.querySelector("h2")?.textContent).toBe("Culto de domingo");
  });

  it("canManage=false: sem rodapé de ações", () => {
    render(false);
    expect(container.querySelector(".ds-dialog-foot")).toBeNull();
  });

  it("canManage=true: rodapé com Editar/Excluir", () => {
    render(true);
    const foot = container.querySelector(".ds-dialog-foot");
    expect(foot?.textContent).toContain("Editar");
    expect(foot?.textContent).toContain("Excluir");
  });

  it("Esc fecha (onClose) quando não está ocupado", () => {
    render(true, false);
    pressEscape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc NÃO fecha enquanto busy=true", () => {
    render(true, true);
    pressEscape();
    expect(onClose).not.toHaveBeenCalled();
  });
});
