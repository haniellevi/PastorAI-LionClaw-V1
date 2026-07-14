// @vitest-environment jsdom
/**
 * M7B-Visual-W1 (realinhamento estrutural da navegação): BottomNav precisa
 * compartilhar a MESMA rota ativa da Sidebar (mesmo contrato de dado —
 * lib/navigation.ts — e mesma semântica aria-current="page").
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PermissionsProvider } from "@/lib/permissions-context";
import { NAV_SECTIONS } from "@/lib/navigation";

const authState = vi.hoisted(() => ({
  roles: ["pastor"] as string[],
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { roles: authState.roles } }),
}));

const { BottomNav } = await import("./BottomNav");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onMore = vi.fn();

function render() {
  act(() => {
    root.render(h(PermissionsProvider, null, h(BottomNav, { onMore, menuOpen: false })));
  });
}

function setHash(route: string) {
  act(() => {
    window.location.hash = `#${route}`;
  });
}

beforeEach(() => {
  authState.roles = ["pastor"];
  onMore.mockReset();
  window.location.hash = "";
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("BottomNav — contrato de rota compartilhado com a Sidebar", () => {
  it("todo atalho fixo do BottomNav existe como screenId em NAV_SECTIONS (evita drift entre os dois)", () => {
    const sidebarTargets = new Set(
      NAV_SECTIONS.flatMap((s) => [
        ...(s.items ?? []).map((i) => i.target),
        ...(s.stages ?? []).map((st) => st.head.target),
      ]),
    );
    render();
    const hrefs = Array.from(container.querySelectorAll(".bn-item[href]")).map((el) =>
      el.getAttribute("href")!.replace("#", ""),
    );
    expect(hrefs.length).toBeGreaterThan(0);
    for (const target of hrefs) {
      expect(sidebarTargets.has(target)).toBe(true);
    }
  });

  it("rota vigente = dashboard: atalho 'Hoje' fica active com aria-current=page", () => {
    setHash("dashboard");
    render();
    const items = Array.from(container.querySelectorAll(".bn-item")) as HTMLAnchorElement[];
    const hoje = items.find((el) => el.textContent?.includes("Hoje"))!;
    expect(hoje.classList.contains("active")).toBe(true);
    expect(hoje.getAttribute("aria-current")).toBe("page");

    const conversas = items.find((el) => el.textContent?.includes("Conversas"))!;
    expect(conversas.classList.contains("active")).toBe(false);
  });

  it("rota vigente = inbox: atalho 'Conversas' fica active, 'Hoje' não", () => {
    setHash("inbox");
    render();
    const items = Array.from(container.querySelectorAll(".bn-item")) as HTMLAnchorElement[];
    const conversas = items.find((el) => el.textContent?.includes("Conversas"))!;
    const hoje = items.find((el) => el.textContent?.includes("Hoje"))!;
    expect(conversas.classList.contains("active")).toBe(true);
    expect(hoje.classList.contains("active")).toBe(false);
  });

  it("'Mais' nunca é active (é ação, não rota) e expõe aria-controls do drawer da Sidebar", () => {
    setHash("dashboard");
    render();
    const mais = Array.from(container.querySelectorAll(".bn-item")).find(
      (el) => el.tagName === "BUTTON",
    ) as HTMLButtonElement;
    expect(mais.classList.contains("active")).toBe(false);
    expect(mais.getAttribute("aria-controls")).toBe("shell-drawer");
  });
});
