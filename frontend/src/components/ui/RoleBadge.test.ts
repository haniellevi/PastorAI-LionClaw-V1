// @vitest-environment jsdom
/**
 * Wave Visual W2: RoleBadge/RoleBadgeList consolidam .rchip (Topbar) e .rt
 * (RolePick/RoleTags) numa única pílula de papel — cobre classe/rótulo por
 * papel (lead vs não-lead) e a ordenação por ROLE_ORDER da lista.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Role } from "@/lib/roles";

import { RoleBadge, RoleBadgeList } from "./RoleBadge";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

describe("RoleBadge — pílula única de papel (Wave Visual W2)", () => {
  it("papel de liderança (pastor) ganha a classe 'lead' e o rótulo por extenso", () => {
    render(h(RoleBadge, { role: "pastor" as Role }));
    const chip = container.querySelector(".role-chip") as HTMLSpanElement;
    expect(chip).not.toBeNull();
    expect(chip.classList.contains("lead")).toBe(true);
    expect(chip.textContent).toBe("Pastor");
  });

  it("papel sem liderança (membro) NÃO ganha a classe 'lead'", () => {
    render(h(RoleBadge, { role: "membro" as Role }));
    const chip = container.querySelector(".role-chip") as HTMLSpanElement;
    expect(chip.classList.contains("lead")).toBe(false);
    expect(chip.textContent).toBe("Membro");
  });

  it("operador (sem liderança) também não ganha 'lead'", () => {
    render(h(RoleBadge, { role: "operador" as Role }));
    const chip = container.querySelector(".role-chip") as HTMLSpanElement;
    expect(chip.classList.contains("lead")).toBe(false);
    expect(chip.textContent).toBe("Operador");
  });
});

describe("RoleBadgeList — papéis acumulados ordenados (Topbar + RoleTags/#equipe)", () => {
  it("renderiza um chip por papel, ordenado por ROLE_ORDER independente da ordem de entrada", () => {
    render(h(RoleBadgeList, { roles: ["membro", "admin", "lider_celula"] as Role[] }));
    const chips = Array.from(container.querySelectorAll(".role-chip"));
    expect(chips.map((c) => c.textContent)).toEqual(["Administrador", "Líder de Célula", "Membro"]);
  });

  it("papéis de liderança (admin, lider_celula) ganham 'lead'; membro não", () => {
    render(h(RoleBadgeList, { roles: ["membro", "admin", "lider_celula"] as Role[] }));
    const chips = Array.from(container.querySelectorAll(".role-chip"));
    const byLabel = Object.fromEntries(chips.map((c) => [c.textContent, c.classList.contains("lead")]));
    expect(byLabel["Administrador"]).toBe(true);
    expect(byLabel["Líder de Célula"]).toBe(true);
    expect(byLabel["Membro"]).toBe(false);
  });

  it("lista vazia não renderiza nenhum chip", () => {
    render(h(RoleBadgeList, { roles: [] as Role[] }));
    expect(container.querySelectorAll(".role-chip")).toHaveLength(0);
  });
});
