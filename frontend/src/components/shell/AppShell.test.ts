// @vitest-environment jsdom
/**
 * M7B-Visual-W1 (revisão externa, achado #2 — contrato central): Sidebar e
 * BottomNav têm de concordar na MESMA rota já resolvida pelo AppShell, nunca
 * cada um recalculando a partir do hash cru — inclusive quando o deep-link
 * pedido é bloqueado (ex.: tela "em breve") e o AppShell normaliza para
 * #dashboard. Antes desta correção, o BottomNav lia o hash cru via seu próprio
 * useHashRoute(), então podia mostrar um item ativo diferente da Sidebar por
 * um instante (até o hashchange do redirect chegar até ele).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PermissionsProvider } from "@/lib/permissions-context";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: {
      appUserId: "u1",
      churchId: "c1",
      email: "ana@example.com",
      nome: "Ana Pastora",
      chatNome: null,
      roles: ["pastor"],
      isOwner: false,
      igrejaNome: "Igreja Teste",
      igrejaLogoUrl: null,
    },
    logout: vi.fn(),
  }),
}));

// Telas reais (dashboard/inbox) têm suas próprias buscas de dados e efeitos —
// fora do escopo deste teste de contrato de navegação, então viram stubs.
vi.mock("@/components/dashboard/DashboardScreen", () => ({
  DashboardScreen: () => null,
}));
vi.mock("@/components/inbox/InboxScreen", () => ({
  InboxScreen: () => null,
}));

const { AppShell } = await import("./AppShell");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function render() {
  act(() => {
    root.render(h(PermissionsProvider, null, h(AppShell)));
  });
}

beforeEach(() => {
  // jsdom não implementa matchMedia — useDrawerA11y (Gate 6) e algumas telas
  // consultam o breakpoint mobile no mount. Sempre "não é mobile" basta aqui.
  window.matchMedia =
    window.matchMedia ??
    ((query: string) =>
      ({
        matches: false,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  window.location.hash = "";
});

describe("AppShell — Sidebar e BottomNav concordam na rota já resolvida", () => {
  it("deep-link bloqueado (#universidade-vida, locked): AppShell resolve pra #dashboard e Sidebar+BottomNav mostram EXATAMENTE UM aria-current=page cada, no mesmo alvo", () => {
    window.location.hash = "#universidade-vida";
    render();

    // AppShell normalizou o hash (rota bloqueada não é o que fica na URL).
    expect(window.location.hash).toBe("#dashboard");

    const current = container.querySelectorAll('[aria-current="page"]');
    expect(current).toHaveLength(2); // 1 nav-item (Sidebar) + 1 bn-item (BottomNav)

    const sidebarActive = container.querySelector(".nav-item.active");
    const bottomNavActive = container.querySelector(".bn-item.active");
    expect(sidebarActive).not.toBeNull();
    expect(bottomNavActive).not.toBeNull();

    // Mesma rota resolvida (#dashboard) nos dois — não o alvo bloqueado pedido.
    expect(sidebarActive!.getAttribute("aria-label")).toBe("Painel de Hoje");
    expect(bottomNavActive!.getAttribute("href")).toBe("#dashboard");
    expect(bottomNavActive!.textContent).toContain("Hoje");
  });

  it("rota permitida direto (#inbox): Sidebar e BottomNav concordam sem precisar de redirect", () => {
    window.location.hash = "#inbox";
    render();

    expect(window.location.hash).toBe("#inbox");
    const current = container.querySelectorAll('[aria-current="page"]');
    expect(current).toHaveLength(2);

    const bottomNavActive = container.querySelector(".bn-item.active");
    expect(bottomNavActive!.getAttribute("href")).toBe("#inbox");
  });
});
