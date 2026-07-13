// @vitest-environment jsdom
/**
 * Gate 6.1 (P1 — drawer mobile verdadeiramente acessível): prova em DOM real
 * (jsdom + React) que o useDrawerA11y:
 *  - fechado em mobile: sidebar `inert` (fora do tab order/árvore de a11y);
 *  - aberto: foco entra no drawer, Tab/Shift+Tab ficam contidos (trap), o
 *    conteúdo atrás (main/bottom-nav) fica `inert` e o scroll REAL da .screen
 *    (e do body) é bloqueado;
 *  - Escape fecha e o foco retorna ao gatilho;
 *  - cruzar o breakpoint para desktop com o drawer aberto fecha e remove locks.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve", que o
 * pipeline do vitest não compila — e o markup do harness fica explícito.
 */
import { act, createElement as h, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SHELL_DRAWER_ID, drawerSidebarClass, useDrawerA11y } from "./useDrawerA11y";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* matchMedia controlável: `mobile` decide (max-width: 860px). */
let mobile = true;
const mqListeners = new Set<() => void>();
function installMatchMedia() {
  window.matchMedia = ((query: string) =>
    ({
      get matches() {
        return mobile;
      },
      media: query,
      addEventListener: (_: string, cb: () => void) => mqListeners.add(cb),
      removeEventListener: (_: string, cb: () => void) => mqListeners.delete(cb),
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
}
function setViewportMobile(next: boolean) {
  mobile = next;
  mqListeners.forEach((cb) => cb());
}

function btn(id: string, label: string): ReactNode {
  return h("button", { type: "button", id, key: id }, label);
}

function Shell({ open, onClose }: { open: boolean; onClose: () => void }) {
  useDrawerA11y(open, onClose);
  return h(
    "div",
    { className: "app" },
    h(
      "nav",
      {
        id: SHELL_DRAWER_ID,
        className: "sidebar",
        "aria-label": "Menu principal",
        tabIndex: -1,
        key: "sidebar",
      },
      btn("nav1", "Painel de Hoje"),
      btn("nav2", "Sair"),
    ),
    h(
      "main",
      { className: "main", key: "main" },
      h("div", { className: "screen" }, btn("atras", "Conteúdo atrás")),
    ),
    h("nav", { className: "bottom-nav", key: "bn" }, btn("mais", "Mais")),
  );
}

let container: HTMLDivElement;
let root: Root;
const onClose = vi.fn();

function render(open: boolean) {
  act(() => {
    root.render(h(Shell, { open, onClose }));
  });
}

function pressKey(key: string, shiftKey = false) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
  });
}

const drawer = () => document.getElementById(SHELL_DRAWER_ID)!;
const screenEl = () => document.querySelector<HTMLElement>(".screen")!;

beforeEach(() => {
  mobile = true;
  mqListeners.clear();
  onClose.mockReset();
  installMatchMedia();
  // jsdom não implementa layout: offsetParent (usado pelo getFocusable para
  // filtrar invisíveis) vira o pai direto — todos os botões contam. Elementos
  // com data-hidden simulam display:none (offsetParent null).
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      const el = this as HTMLElement;
      return el.dataset.hidden ? null : el.parentElement;
    },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.style.overflow = "";
});

describe("useDrawerA11y", () => {
  it("fechado em mobile: sidebar inert; em desktop: interativa", () => {
    render(false);
    expect(drawer().hasAttribute("inert")).toBe(true);
    setViewportMobile(false);
    expect(drawer().hasAttribute("inert")).toBe(false);
  });

  it("aberto: foco no drawer, conteúdo atrás inert e scroll da .screen bloqueado", () => {
    render(false);
    document.getElementById("mais")!.focus();
    render(true);

    expect(drawer().hasAttribute("inert")).toBe(false);
    expect(document.activeElement?.id).toBe("nav1");
    expect(document.querySelector(".main")!.hasAttribute("inert")).toBe(true);
    expect(document.querySelector(".bottom-nav")!.hasAttribute("inert")).toBe(true);
    expect(screenEl().style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("focus trap: Tab cicla dentro do drawer (e Shift+Tab volta)", () => {
    render(false);
    document.getElementById("mais")!.focus();
    render(true);

    pressKey("Tab"); // nav1 -> nav2
    expect(document.activeElement?.id).toBe("nav2");
    pressKey("Tab"); // nav2 -> wrap p/ nav1 (nunca sai do drawer)
    expect(document.activeElement?.id).toBe("nav1");
    pressKey("Tab", true); // Shift+Tab: nav1 -> nav2
    expect(document.activeElement?.id).toBe("nav2");
  });

  it("Escape fecha e o foco retorna ao gatilho; locks removidos", () => {
    render(false);
    document.getElementById("mais")!.focus();
    render(true);

    pressKey("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    render(false); // o pai reage ao onClose fechando

    expect(document.activeElement?.id).toBe("mais");
    expect(document.querySelector(".main")!.hasAttribute("inert")).toBe(false);
    expect(document.querySelector(".bottom-nav")!.hasAttribute("inert")).toBe(false);
    expect(screenEl().style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(drawer().hasAttribute("inert")).toBe(true); // mobile fechado de novo
  });

  it("cruzar para desktop com o drawer aberto fecha e remove todos os locks", () => {
    render(false);
    document.getElementById("mais")!.focus();
    render(true);

    act(() => setViewportMobile(false));
    expect(onClose).toHaveBeenCalledTimes(1);
    // No desktop o gatilho mobile some (display:none) — o foco NÃO pode ir
    // para ele: cai no primeiro focável da sidebar, agora visível (Gate 6.2).
    document.getElementById("mais")!.dataset.hidden = "1";
    render(false);

    expect(document.activeElement?.id).toBe("nav1");
    expect(document.querySelector(".main")!.hasAttribute("inert")).toBe(false);
    expect(screenEl().style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(drawer().hasAttribute("inert")).toBe(false); // desktop: sidebar ativa
  });

  it("drawerSidebarClass: aberto em mobile NUNCA colapsado; colapso só desktop", () => {
    // desktop colapsado → muda p/ mobile → abre: largura completa (sem .collapsed)
    expect(drawerSidebarClass(true, true)).toBe("sidebar open");
    expect(drawerSidebarClass(true, false)).toBe("sidebar collapsed");
    expect(drawerSidebarClass(false, true)).toBe("sidebar open");
    expect(drawerSidebarClass(false, false)).toBe("sidebar");
  });
});
