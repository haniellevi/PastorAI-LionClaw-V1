// @vitest-environment jsdom
/**
 * W4A — LinkCellModal migrado para o DsDialog. Cobre o shell acessível
 * (abertura, fechamento por Fechar/backdrop/Esc, foco inicial, retorno de foco,
 * focus trap) e o bloqueio de fechamento enquanto `busy` (correção intencional:
 * antes dava para fechar durante o vínculo). As linhas do seletor já bloqueadas
 * (célula inativa/sem líder) continuam bloqueadas — e as demais bloqueiam no busy.
 *
 * Harness sem @testing-library: createRoot + act (ver ds/Dialog.test.ts).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getFocusable } from "@/components/ds/a11y";
import type { Cell } from "@/lib/dashboard-api";

import { LinkCellModal } from "./LinkCellModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const cells: Cell[] = [
  { id: "c1", nome: "Célula Alfa", liderId: "l1", ativo: true }, // disponível
  { id: "c2", nome: "Célula Beta", liderId: null, ativo: true }, // bloqueada (sem líder)
];

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement;
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

function panel(): HTMLElement {
  const el = container.querySelector<HTMLElement>('[role="dialog"]');
  if (!el) throw new Error("dialog não encontrado");
  return el;
}
function overlay(): HTMLElement {
  const el = container.querySelector<HTMLElement>(".ds-overlay");
  if (!el) throw new Error("overlay não encontrado");
  return el;
}
function closeButton(): HTMLElement {
  const el = container.querySelector<HTMLElement>('[aria-label="Fechar"]');
  if (!el) throw new Error("botão Fechar não encontrado");
  return el;
}
function rowByName(name: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll<HTMLButtonElement>(".picker-row")).find((b) =>
    (b.textContent ?? "").includes(name),
  );
  if (!btn) throw new Error(`linha "${name}" não encontrada`);
  return btn;
}
function pressKey(key: string, shiftKey = false) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
  });
}
function fire(el: Element, type: "click" | "mousedown") {
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true }));
  });
}
function renderModal(opts: { busy?: boolean; onClose?: () => void } = {}): () => void {
  const onClose = opts.onClose ?? vi.fn();
  act(() => {
    root.render(
      <LinkCellModal
        cells={cells}
        contactName="Maria Silva"
        busy={opts.busy ?? false}
        error={null}
        onClose={onClose}
        onLink={vi.fn()}
      />,
    );
  });
  return onClose;
}

describe("LinkCellModal — DsDialog acessível", () => {
  it("abre como dialog modal com título e nome do contato", () => {
    renderModal();
    expect(panel().getAttribute("aria-modal")).toBe("true");
    expect(container.textContent).toContain("Conectar à célula");
    expect(container.textContent).toContain("Maria Silva");
  });

  it("fecha pelo botão Fechar", () => {
    const onClose = renderModal();
    fire(closeButton(), "click");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha por clique no overlay (backdrop)", () => {
    const onClose = renderModal();
    fire(overlay(), "mousedown");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha por Esc", () => {
    const onClose = renderModal();
    pressKey("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("foco inicial vai para o primeiro focável (botão Fechar do cabeçalho)", () => {
    renderModal();
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Fechar");
  });

  it("retorna o foco ao elemento que abriu quando fecha", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    renderModal();
    expect(document.activeElement).not.toBe(opener);

    act(() => root.render(null));
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("Tab não escapa do diálogo (mantém o foco dentro do painel)", () => {
    renderModal();
    const focusables = getFocusable(panel());
    focusables[focusables.length - 1]!.focus();
    pressKey("Tab");
    expect(panel().contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(focusables[0]);
  });

  describe("durante o vínculo (busy): fechamento bloqueado", () => {
    it("Esc não fecha", () => {
      const onClose = renderModal({ busy: true });
      pressKey("Escape");
      expect(onClose).not.toHaveBeenCalled();
    });

    it("clique no overlay não fecha", () => {
      const onClose = renderModal({ busy: true });
      fire(overlay(), "mousedown");
      expect(onClose).not.toHaveBeenCalled();
    });

    it("botão Fechar não fecha", () => {
      const onClose = renderModal({ busy: true });
      fire(closeButton(), "click");
      expect(onClose).not.toHaveBeenCalled();
    });

    it("as linhas do seletor permanecem bloqueadas", () => {
      renderModal({ busy: true });
      expect(rowByName("Célula Alfa").disabled).toBe(true); // disponível fora do busy
      expect(rowByName("Célula Beta").disabled).toBe(true); // já bloqueada, continua
    });
  });
});
