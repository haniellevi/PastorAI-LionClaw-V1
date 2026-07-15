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
import { ROLE_DEFS, sortedRoles, type Role } from "@/lib/roles";

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

/**
 * Wave Visual W2 (revisão externa, reforço #2): Topbar passou a delegar a
 * renderização dos papéis pra RoleBadgeList (era JSX inline). Cobre o
 * integration point real — user.roles acumulados chegando ao DOM do Topbar —
 * pra não depender só do teste unitário de RoleBadge isolado.
 */
function renderWithRoles(roles: Role[]) {
  const multiRoleUser: SessionUser = {
    appUserId: "u2",
    churchId: "c1",
    email: "lider@example.com",
    nome: "Líder Multi",
    chatNome: null,
    roles,
    isOwner: false,
    igrejaNome: "Igreja Teste",
    igrejaLogoUrl: null,
  };
  act(() => {
    root.render(h(Topbar, { user: multiRoleUser, route: "dashboard", onMenuToggle: vi.fn() }));
  });
}

describe("Topbar — papéis acumulados (Wave Visual W2)", () => {
  it("renderiza um chip por papel acumulado, todos presentes", () => {
    const roles: Role[] = ["membro", "admin", "lider_celula"];
    renderWithRoles(roles);
    const chips = Array.from(container.querySelectorAll(".who .role-chip"));
    expect(chips).toHaveLength(roles.length);
  });

  it("ordena os chips pela fonte canônica (sortedRoles de @/lib/roles), não pela ordem de entrada", () => {
    const roles: Role[] = ["membro", "admin", "lider_celula"];
    renderWithRoles(roles);
    const chips = Array.from(container.querySelectorAll(".who .role-chip"));
    const expectedOrder = sortedRoles(roles).map((r) => ROLE_DEFS[r].label);
    expect(chips.map((c) => c.textContent)).toEqual(expectedOrder);
    // a ordem de entrada era membro/admin/lider_celula — a saída não pode ser igual a essa ordem crua.
    expect(chips.map((c) => c.textContent)).not.toEqual(roles.map((r) => ROLE_DEFS[r].label));
  });

  it("rótulo de cada chip é o texto completo de ROLE_DEFS — sem truncar/abreviar", () => {
    const roles: Role[] = ["lider_consol", "lider_mult", "operador"];
    renderWithRoles(roles);
    const chips = Array.from(container.querySelectorAll(".who .role-chip"));
    for (const chip of chips) {
      const match = Object.values(ROLE_DEFS).find((def) => def.label === chip.textContent);
      expect(match, `chip com texto "${chip.textContent}" não bate com nenhum ROLE_DEFS.label`).toBeTruthy();
    }
  });

  it("papéis de liderança recebem 'lead'; papéis sem liderança não — mesmo critério de ROLE_DEFS", () => {
    const roles: Role[] = ["pastor", "membro", "operador"];
    renderWithRoles(roles);
    const chips = Array.from(container.querySelectorAll(".who .role-chip"));
    const byLabel = Object.fromEntries(chips.map((c) => [c.textContent, c.classList.contains("lead")]));
    expect(byLabel[ROLE_DEFS.pastor.label]).toBe(true);
    expect(byLabel[ROLE_DEFS.membro.label]).toBe(false);
    expect(byLabel[ROLE_DEFS.operador.label]).toBe(false);
  });

  it("papel único continua renderizando exatamente 1 chip (sem regressão do caso simples)", () => {
    renderWithRoles(["pastor"]);
    const chips = container.querySelectorAll(".who .role-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0]?.textContent).toBe(ROLE_DEFS.pastor.label);
  });
});
