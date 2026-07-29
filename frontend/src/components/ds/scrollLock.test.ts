// @vitest-environment jsdom
/**
 * PR213 — coordenador ÚNICO de scroll lock (ds/scrollLock).
 *
 * Regressão do bug de locks encadeados: Dialog e drawer salvavam/restauravam o
 * inline `overflow` cada um por si. Com dois locks vivos, o segundo fotografava
 * o "hidden" do primeiro — fechar FORA de ordem destravava a página com um
 * overlay ainda aberto e, no fechamento final, gravava "hidden" de volta
 * (página travada para sempre).
 *
 * Matriz coberta, sempre com valores inline PREEXISTENTES em `body` e `.screen`
 * (para provar que a restauração é exata, e não um reset para ""):
 *  1. Dialog A + Dialog B — fechar A→B (fora de ordem) e B→A (LIFO);
 *  2. drawer + Dialog     — fechar drawer→Dialog e Dialog→drawer.
 * Em todos: após o fechamento INTERMEDIÁRIO os dois alvos seguem travados;
 * só após o ÚLTIMO os valores originais voltam.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SHELL_DRAWER_ID, useDrawerA11y } from "@/components/shell/useDrawerA11y";

import { Dialog } from "./Dialog";
import { lockScroll } from "./scrollLock";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* matchMedia controlável (mesmo harness do useDrawerA11y.test): mobile = true. */
const mqListeners = new Set<() => void>();
function installMatchMedia() {
  window.matchMedia = ((query: string) =>
    ({
      matches: true,
      media: query,
      addEventListener: (_: string, cb: () => void) => mqListeners.add(cb),
      removeEventListener: (_: string, cb: () => void) => mqListeners.delete(cb),
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
}

const noop = vi.fn();

function btn(id: string, label: string): ReactNode {
  return h("button", { type: "button", id, key: id }, label);
}

/** Shell real (drawer + .screen) com dois Dialogs independentes por cima. */
function Harness({ drawer, a, b }: { drawer: boolean; a: boolean; b: boolean }) {
  useDrawerA11y(drawer, noop);
  return h(
    "div",
    { className: "app" },
    h(
      "nav",
      { id: SHELL_DRAWER_ID, className: "sidebar", tabIndex: -1, key: "nav" },
      btn("nav1", "Painel de Hoje"),
    ),
    h("main", { className: "main", key: "main" }, h("div", { className: "screen" }, btn("atras", "Atrás"))),
    h(Dialog, { open: a, onClose: noop, title: "A", key: "a", children: btn("ca", "Ação A") }),
    h(Dialog, { open: b, onClose: noop, title: "B", key: "b", children: btn("cb", "Ação B") }),
  );
}

let container: HTMLDivElement;
let root: Root;

/** Estado corrente do harness — cada render muda UM flag por vez. */
let state = { drawer: false, a: false, b: false };
function render(next: Partial<typeof state>) {
  state = { ...state, ...next };
  act(() => {
    root.render(h(Harness, state));
  });
}

const screenEl = () => document.querySelector<HTMLElement>(".screen")!;

function expectLocked() {
  expect(document.body.style.overflow).toBe("hidden");
  expect(screenEl().style.overflow).toBe("hidden");
}
function expectRestored() {
  expect(document.body.style.overflow).toBe("visible");
  expect(screenEl().style.overflow).toBe("auto");
}

/** Monta fechado e planta os valores inline PREEXISTENTES nos dois alvos. */
function mountWithPreexistingInline() {
  render({ drawer: false, a: false, b: false });
  document.body.style.overflow = "visible";
  screenEl().style.overflow = "auto";
}

beforeEach(() => {
  mqListeners.clear();
  noop.mockReset();
  installMatchMedia();
  // jsdom não implementa layout: offsetParent (filtro do getFocusable) vira o
  // pai direto — todos os controles contam como visíveis.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  state = { drawer: false, a: false, b: false };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.style.overflow = "";
});

describe("scrollLock — Dialog sobre Dialog", () => {
  it("fechar FORA de ordem (A→B): segue travado até o último; restauração exata", () => {
    mountWithPreexistingInline();

    render({ a: true });
    expectLocked();
    render({ b: true });
    expectLocked();

    // Fechamento intermediário do PRIMEIRO dono: B continua aberto.
    render({ a: false });
    expectLocked();

    render({ b: false });
    expectRestored();
  });

  it("fechar em LIFO (B→A): mesmo contrato", () => {
    mountWithPreexistingInline();

    render({ a: true });
    render({ b: true });
    expectLocked();

    render({ b: false });
    expectLocked();

    render({ a: false });
    expectRestored();
  });
});

describe("scrollLock — drawer do shell + Dialog", () => {
  it("fechar o drawer primeiro NÃO destrava com o Dialog aberto", () => {
    mountWithPreexistingInline();

    render({ drawer: true });
    expectLocked();
    render({ a: true });
    expectLocked();

    render({ drawer: false });
    expectLocked();

    render({ a: false });
    expectRestored();
  });

  it("fechar o Dialog primeiro NÃO destrava com o drawer aberto", () => {
    mountWithPreexistingInline();

    render({ drawer: true });
    render({ a: true });
    expectLocked();

    render({ a: false });
    expectLocked();

    render({ drawer: false });
    expectRestored();
  });
});

describe("scrollLock — release idempotente", () => {
  it("chamar o release duas vezes não libera o lock de outro dono", () => {
    document.body.style.overflow = "visible";
    const first = lockScroll();
    const second = lockScroll();
    expect(document.body.style.overflow).toBe("hidden");

    first();
    first(); // repetido: não pode contar como a liberação do `second`
    expect(document.body.style.overflow).toBe("hidden");

    second();
    expect(document.body.style.overflow).toBe("visible");
  });
});
