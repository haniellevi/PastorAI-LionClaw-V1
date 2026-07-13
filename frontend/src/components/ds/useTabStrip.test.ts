// @vitest-environment jsdom
/**
 * Gate 6.4 (finding P2 do Codex no PR #164): host persistente do useTabStrip
 * (JourneyStepper no AppShell) monta SEM a faixa no DOM (retorna null fora da
 * Jornada). Com o efeito de listeners preso a `[]`, a faixa que aparece depois
 * (navegação client-side p/ #consolidar) nunca ganhava data-at-start/at-end
 * nem reagia a scroll/resize. Este teste FALHA no código antigo: o efeito
 * agora re-roda quando activeKey muda e a faixa existe.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve", que o
 * pipeline do vitest não compila.
 */
import { act, createElement as h, useRef, type RefObject } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTabStrip } from "./useTabStrip";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function Host({ show, activeKey }: { show: boolean; activeKey: string }) {
  const listRef = useRef<HTMLElement | null>(null);
  const wrapRef = useRef<HTMLElement | null>(null);
  useTabStrip(listRef as RefObject<HTMLElement | null>, wrapRef, activeKey);
  if (!show) return null;
  // Estrutura mínima esperada pelo hook: wrap > scroller > list.
  return h(
    "nav",
    { ref: wrapRef as RefObject<HTMLElement>, id: "wrap" },
    h(
      "div",
      { id: "scroller" },
      h("div", { ref: listRef as RefObject<HTMLDivElement>, id: "list" }),
    ),
  );
}

let container: HTMLDivElement;
let root: Root;

function render(show: boolean, activeKey: string) {
  act(() => {
    root.render(h(Host, { show, activeKey }));
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

describe("useTabStrip — faixa que aparece depois do mount (Gate 6.4)", () => {
  it("monta sem faixa (null) e, quando a rota muda e a faixa aparece, define data-at-* e reage a scroll", () => {
    // 1) host monta FORA da Jornada: nada no DOM, efeito sem refs.
    render(false, "dashboard");
    expect(document.getElementById("wrap")).toBeNull();

    // 2) navegação client-side: activeKey muda e a faixa aparece.
    render(true, "consolidar");
    const wrap = document.getElementById("wrap")!;
    expect(wrap.dataset.atEnd).toBeDefined();
    expect(wrap.dataset.atStart).toBeDefined();

    // 3) a faixa REAGE a scroll: simula overflow real no scroller.
    const scroller = document.getElementById("scroller")!;
    Object.defineProperty(scroller, "scrollWidth", { configurable: true, value: 300 });
    Object.defineProperty(scroller, "clientWidth", { configurable: true, value: 100 });
    scroller.scrollLeft = 50;
    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });
    expect(wrap.dataset.atStart).toBe("false");
    expect(wrap.dataset.atEnd).toBe("false");

    scroller.scrollLeft = 200; // 200 + 100 >= 300 → fim
    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });
    expect(wrap.dataset.atEnd).toBe("true");

    scroller.scrollLeft = 0; // volta ao início
    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });
    expect(wrap.dataset.atStart).toBe("true");
  });

  it("re-render com novo activeKey não duplica listeners (cleanup antes do re-registro)", () => {
    render(true, "consolidar");
    const scroller = document.getElementById("scroller")!;
    const add = vi.spyOn(scroller, "addEventListener");
    const remove = vi.spyOn(scroller, "removeEventListener");

    render(true, "consol-individual"); // activeKey muda → cleanup + re-registro
    const adds = add.mock.calls.filter(([t]) => t === "scroll").length;
    const removes = remove.mock.calls.filter(([t]) => t === "scroll").length;
    expect(adds).toBe(1);
    expect(removes).toBe(1); // removeu o antigo antes de adicionar o novo
  });
});
