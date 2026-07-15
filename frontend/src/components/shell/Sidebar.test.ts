// @vitest-environment jsdom
/**
 * M7B-Visual-W1 (realinhamento estrutural da navegação):
 *  - item ativo tem UMA affordance só (aria-current="page" + classe "active");
 *    o ícone NÃO ganha um segundo tint por cima da linha (regressão da caixa
 *    dentro de caixa é coberta em globals.css.test.ts, em CSS-fonte);
 *  - nome acessível explícito via aria-label (vale colapsado e expandido);
 *  - item locked soma "— disponível em breve" ao aria-label (nunca navega).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PermissionsProvider } from "@/lib/permissions-context";
import type { NavSection } from "@/lib/navigation";
import type { Role } from "@/lib/roles";

import { Sidebar } from "./Sidebar";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SECTIONS: NavSection[] = [
  {
    id: "gestao",
    label: "Igreja",
    items: [
      { target: "dashboard", label: "Painel de Hoje", icon: "dashboard" },
      { target: "consolidar", label: "Consolidar", icon: "consolidar" },
      { target: "universidade-vida", label: "Universidade da Vida", icon: "university", locked: true },
    ],
  },
];

const user = {
  appUserId: "u1",
  churchId: "c1",
  email: "ana@example.com",
  nome: "Ana Pastora",
  chatNome: null,
  roles: ["pastor"] as Role[],
  isOwner: false,
  igrejaNome: "Igreja Teste",
  igrejaLogoUrl: null,
};

let container: HTMLDivElement;
let root: Root;
const onNavigate = vi.fn();

function render(route: string, collapsed = false, mobileOpen = false) {
  act(() => {
    root.render(
      h(
        PermissionsProvider,
        null,
        h(Sidebar, {
          user,
          route,
          sections: SECTIONS,
          collapsed,
          mobileOpen,
          onNavigate,
          onToggleCollapse: vi.fn(),
          onLogout: vi.fn(),
        }),
      ),
    );
  });
}

beforeEach(() => {
  onNavigate.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("Sidebar — nav-item ativo/aria-label (contrato compartilhado M7B-Visual-W1)", () => {
  it("item da rota vigente: classe active + aria-current=page + aria-label = label", () => {
    render("dashboard");
    const active = container.querySelector(".nav-item.active") as HTMLButtonElement;
    expect(active).not.toBeNull();
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(active.getAttribute("aria-label")).toBe("Painel de Hoje");

    const other = Array.from(container.querySelectorAll(".nav-item")).find(
      (el) => el.textContent?.includes("Consolidar"),
    ) as HTMLButtonElement;
    expect(other.classList.contains("active")).toBe(false);
    expect(other.getAttribute("aria-current")).toBeNull();
  });

  it("item locked: aria-label soma o sufixo, nunca fica active e não navega ao clicar", () => {
    render("dashboard");
    const locked = Array.from(container.querySelectorAll(".nav-item.locked")) as HTMLButtonElement[];
    expect(locked).toHaveLength(1);
    expect(locked[0]!.getAttribute("aria-label")).toBe("Universidade da Vida — disponível em breve");
    expect(locked[0]!.getAttribute("aria-disabled")).toBe("true");

    act(() => locked[0]!.click());
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("colapsado: aria-label do item ativo continua presente (nome acessível não depende do rótulo visível)", () => {
    render("dashboard", true);
    const active = container.querySelector(".nav-item.active") as HTMLButtonElement;
    expect(active.getAttribute("aria-label")).toBe("Painel de Hoje");
    expect(container.querySelector(".sidebar")?.classList.contains("collapsed")).toBe(true);
  });

  it("colapsado + locked: aria-label com sufixo, nunca active, não navega, e o flyout mostra o rótulo curto no foco (revisão externa achado #3)", () => {
    render("dashboard", true);
    const locked = container.querySelector(".nav-item.locked") as HTMLButtonElement;
    expect(locked.getAttribute("aria-label")).toBe("Universidade da Vida — disponível em breve");
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked.classList.contains("active")).toBe(false);

    act(() => locked.click());
    expect(onNavigate).not.toHaveBeenCalled();

    act(() => locked.focus());
    const tip = container.querySelector(".nav-tip");
    // O flyout usa o rótulo curto (o sufixo "em breve" já está no aria-label,
    // anunciado por leitor de tela — repeti-lo no tooltip visual seria ruído).
    expect(tip?.textContent).toBe("Universidade da Vida");

    act(() => locked.blur());
    expect(container.querySelector(".nav-tip")).toBeNull();
  });

  it("colapsado: focar/desfocar um item NUNCA mexe no scroll do .nav-scroll (revisão externa achado #1 — overflow/scrollTop preservados)", () => {
    render("dashboard", true);
    const navScroll = container.querySelector(".nav-scroll") as HTMLDivElement;
    navScroll.scrollTop = 42;

    const active = container.querySelector(".nav-item.active") as HTMLButtonElement;
    act(() => active.focus());
    // O flyout do tooltip apareceu...
    expect(container.querySelector(".nav-tip")).not.toBeNull();
    // ...mas o container de scroll não foi tocado: mesmo scrollTop, mesma
    // classe, sem style inline (nada no código muda overflow em runtime).
    expect(navScroll.scrollTop).toBe(42);
    expect(navScroll.className).toBe("nav-scroll");
    expect(navScroll.getAttribute("style")).toBeNull();

    act(() => active.blur());
    expect(navScroll.scrollTop).toBe(42);
    expect(container.querySelector(".nav-tip")).toBeNull();
  });
});

describe("Sidebar — flyout do tooltip só no rail 64px de verdade (revisão externa, 2ª rodada)", () => {
  it("collapsed=true + mobileOpen=true: hover/foco NÃO renderiza .nav-tip (drawer mobile é sempre largura completa, Gate 6.2)", () => {
    render("dashboard", true, true);
    // Sem a classe CSS "collapsed" no DOM: o drawer mobile aberto ignora a
    // preferência de desktop (drawerSidebarClass já cobre isso).
    expect(container.querySelector(".sidebar")?.classList.contains("collapsed")).toBe(false);
    expect(container.querySelector(".sidebar")?.classList.contains("open")).toBe(true);

    const active = container.querySelector(".nav-item.active") as HTMLButtonElement;
    act(() => active.focus());
    expect(container.querySelector(".nav-tip")).toBeNull();

    act(() => active.blur());
    expect(container.querySelector(".nav-tip")).toBeNull();
  });

  it("collapsed=true + mobileOpen=false: hover/foco AINDA renderiza .nav-tip (rail 64px de verdade, comportamento preservado)", () => {
    render("dashboard", true, false);
    expect(container.querySelector(".sidebar")?.classList.contains("collapsed")).toBe(true);

    const active = container.querySelector(".nav-item.active") as HTMLButtonElement;
    act(() => active.focus());
    const tip = container.querySelector(".nav-tip");
    expect(tip).not.toBeNull();
    expect(tip!.textContent).toBe("Painel de Hoje");

    act(() => active.blur());
    expect(container.querySelector(".nav-tip")).toBeNull();
  });
});
