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

function render(route: string, collapsed = false) {
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
          mobileOpen: false,
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
});
