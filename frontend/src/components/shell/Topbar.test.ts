// @vitest-environment jsdom
/**
 * M7B-Visual-W1 (revisão externa achado #4): o h1 do Topbar trunca com
 * reticências em telas estreitas (CSS) — o title nativo garante que o mouse
 * ainda vê o texto completo, sem JS/tooltip próprio.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionUser } from "@/lib/auth-context";
import { SCREEN_META } from "@/lib/navigation";

import { Topbar } from "./Topbar";

const user: SessionUser = {
  appUserId: "u1",
  churchId: "c1",
  email: "ana@example.com",
  nome: "Ana Pastora",
  chatNome: null,
  roles: ["pastor"],
  isOwner: false,
  igrejaNome: "Igreja Teste",
  igrejaLogoUrl: null,
};

let container: HTMLDivElement;
let root: Root;

function render(route: string) {
  act(() => {
    root.render(h(Topbar, { user, route, onMenuToggle: vi.fn() }));
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

describe("Topbar — title nativo no h1 truncado", () => {
  it("h1 tem title=texto completo do título (mesmo texto do conteúdo visível)", () => {
    render("dashboard");
    const h1 = container.querySelector("h1")!;
    expect(h1.getAttribute("title")).toBe(SCREEN_META.dashboard!.title);
    expect(h1.textContent).toBe(SCREEN_META.dashboard!.title);
  });

  it("troca de rota: o title acompanha o novo título", () => {
    render("inbox");
    const h1 = container.querySelector("h1")!;
    expect(h1.getAttribute("title")).toBe(SCREEN_META.inbox!.title);
  });
});
