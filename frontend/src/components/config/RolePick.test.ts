// @vitest-environment jsdom
/**
 * Wave Visual W2 (revisão externa, reforço #2): RolePick (seleção de papéis,
 * telas #equipe) e RoleTags (agora delegando pra RoleBadgeList) não tinham
 * teste próprio. Cobre com 2+ papéis: rótulos, estado selecionado/checked,
 * chamada de onToggle e que a nova apresentação (RoleBadgeList) não altera
 * valores/seleção — só o componente visual mudou, não @/lib/roles.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ROLE_DEFS, ROLE_ORDER, sortedRoles, type Role } from "@/lib/roles";

import { RolePick, RoleTags } from "./RolePick";

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(node: Parameters<Root["render"]>[0]) {
  act(() => {
    root.render(node);
  });
}

describe("RolePick — seleção múltipla de papéis (#equipe)", () => {
  const options: Role[] = ["admin", "lider_celula", "membro"];

  it("renderiza um label por opção, na ordem recebida, com o rótulo completo de ROLE_DEFS", () => {
    render(h(RolePick, { options, selected: new Set<Role>(), onToggle: vi.fn() }));
    const labels = Array.from(container.querySelectorAll(".role-pick label span:first-of-type"));
    expect(labels.map((l) => l.textContent)).toEqual(options.map((r) => ROLE_DEFS[r].label));
  });

  it("papéis selecionados ganham classe 'on' e checkbox checked=true; os demais, não", () => {
    const selected = new Set<Role>(["admin", "membro"]);
    render(h(RolePick, { options, selected, onToggle: vi.fn() }));
    const labels = Array.from(container.querySelectorAll(".role-pick label"));
    const state = labels.map((l) => ({
      on: l.classList.contains("on"),
      checked: (l.querySelector("input") as HTMLInputElement).checked,
      value: (l.querySelector("input") as HTMLInputElement).value,
    }));
    expect(state).toEqual([
      { on: true, checked: true, value: "admin" },
      { on: false, checked: false, value: "lider_celula" },
      { on: true, checked: true, value: "membro" },
    ]);
  });

  it("marcar um checkbox chama onToggle com (role, true); desmarcar chama com (role, false)", () => {
    const onToggle = vi.fn();
    const selected = new Set<Role>(["admin"]);
    render(h(RolePick, { options, selected, onToggle }));
    const inputs = Array.from(container.querySelectorAll(".role-pick input")) as HTMLInputElement[];

    const membroInput = inputs.find((i) => i.value === "membro")!;
    act(() => {
      membroInput.click();
    });
    expect(onToggle).toHaveBeenCalledWith("membro", true);

    const adminInput = inputs.find((i) => i.value === "admin")!;
    act(() => {
      adminInput.click();
    });
    expect(onToggle).toHaveBeenCalledWith("admin", false);
  });

  it("disabled propaga pra todos os checkboxes", () => {
    render(h(RolePick, { options, selected: new Set<Role>(), onToggle: vi.fn(), disabled: true }));
    const inputs = Array.from(container.querySelectorAll(".role-pick input")) as HTMLInputElement[];
    expect(inputs.every((i) => i.disabled)).toBe(true);
  });

  it("mantém papel derivado visível e marcado, mas não editável", () => {
    const onToggle = vi.fn();
    render(
      h(RolePick, {
        options,
        selected: new Set<Role>(["lider_celula", "membro"]),
        onToggle,
        locked: { lider_celula: "Gerido pela Central de Células" },
      }),
    );

    const derived = container.querySelector(
      '.role-pick input[value="lider_celula"]',
    ) as HTMLInputElement;
    expect(derived.checked).toBe(true);
    expect(derived.disabled).toBe(true);
    expect(derived.closest("label")?.textContent).toContain("derivado da célula");
    act(() => derived.click());
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("legenda 'liderança'/'membro' reflete ROLE_DEFS[role].lead", () => {
    render(h(RolePick, { options, selected: new Set<Role>(), onToggle: vi.fn() }));
    const rks = Array.from(container.querySelectorAll(".role-pick label .rk")).map((el) => el.textContent);
    expect(rks).toEqual(options.map((r) => (ROLE_DEFS[r].lead ? "liderança" : "membro")));
  });
});

describe("RoleTags — papéis acumulados (agora via RoleBadgeList, #equipe)", () => {
  it("com 2+ papéis, renderiza todos ordenados pela fonte canônica — mesmos valores/rótulos de ROLE_DEFS", () => {
    const roles: Role[] = ["membro", "pastor", "lider_g12"];
    render(h(RoleTags, { roles }));
    const chips = Array.from(container.querySelectorAll(".role-chip"));
    expect(chips).toHaveLength(roles.length);
    expect(chips.map((c) => c.textContent)).toEqual(sortedRoles(roles).map((r) => ROLE_DEFS[r].label));
  });

  it("não perde nem duplica papel algum para o conjunto completo de ROLE_ORDER", () => {
    render(h(RoleTags, { roles: ROLE_ORDER }));
    const chips = Array.from(container.querySelectorAll(".role-chip"));
    expect(chips).toHaveLength(ROLE_ORDER.length);
    expect(new Set(chips.map((c) => c.textContent)).size).toBe(ROLE_ORDER.length);
  });

  it("papéis de liderança continuam marcados 'lead'; a troca de componente não muda esse critério", () => {
    const roles: Role[] = ["lider_mult", "membro"];
    render(h(RoleTags, { roles }));
    const chips = Array.from(container.querySelectorAll(".role-chip"));
    const byLabel = Object.fromEntries(chips.map((c) => [c.textContent, c.classList.contains("lead")]));
    expect(byLabel[ROLE_DEFS.lider_mult.label]).toBe(true);
    expect(byLabel[ROLE_DEFS.membro.label]).toBe(false);
  });
});
