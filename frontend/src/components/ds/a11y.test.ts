import { describe, expect, it } from "vitest";

import { rovingNextIndex, tabDomIds, trapNextIndex } from "./a11y";

describe("trapNextIndex (focus trap do Dialog/Sheet)", () => {
  it("cicla para o primeiro ao passar do último (Tab)", () => {
    expect(trapNextIndex(2, 3, false)).toBe(0);
  });
  it("cicla para o último ao voltar do primeiro (Shift+Tab)", () => {
    expect(trapNextIndex(0, 3, true)).toBe(2);
  });
  it("avança e retrocede dentro da lista", () => {
    expect(trapNextIndex(0, 3, false)).toBe(1);
    expect(trapNextIndex(2, 3, true)).toBe(1);
  });
  it("foco vindo de fora vai para o primeiro (ou último com Shift)", () => {
    expect(trapNextIndex(-1, 3, false)).toBe(0);
    expect(trapNextIndex(-1, 3, true)).toBe(2);
  });
  it("lista vazia não tem alvo", () => {
    expect(trapNextIndex(0, 0, false)).toBe(-1);
  });
});

describe("tabDomIds (regressão Gate 5.1: IDs únicos por instância)", () => {
  const CENTRAL = ["dashboard", "cells", "requests", "notices", "materials"];
  it("duas instâncias com prefixos distintos nunca colidem (mesmos tabIds)", () => {
    const a = CENTRAL.flatMap((t) => Object.values(tabDomIds(":r1:", t)));
    const b = CENTRAL.flatMap((t) => Object.values(tabDomIds(":r2:", t)));
    const todos = [...a, ...b];
    expect(new Set(todos).size).toBe(todos.length);
  });
  it("dentro da instância, tab e panel são únicos por tabId", () => {
    const ids = CENTRAL.flatMap((t) => Object.values(tabDomIds(":r1:", t)));
    expect(new Set(ids).size).toBe(CENTRAL.length * 2);
  });
  it("codificação é injetiva: 'a b', 'a_b' e 'a%20b' nunca colidem (Gate 5.2)", () => {
    const ids = ["a b", "a_b", "a%20b"].map((t) => tabDomIds(":r1:", t).tab);
    expect(new Set(ids).size).toBe(3);
  });
  it("Unicode é codificado sem espaço e sem colisão", () => {
    const a = tabDomIds(":r1:", "gerenciar células");
    const b = tabDomIds(":r1:", "gerenciar celulas");
    expect(a.tab).not.toMatch(/\s/);
    expect(a.tab).not.toBe(b.tab);
    expect(a.panel).not.toBe(b.panel);
  });
});

describe("rovingNextIndex (teclado das Tabs)", () => {
  it("setas avançam e retrocedem com wrap (5 tabs da Central)", () => {
    expect(rovingNextIndex(0, 5, "ArrowRight")).toBe(1);
    expect(rovingNextIndex(4, 5, "ArrowRight")).toBe(0);
    expect(rovingNextIndex(0, 5, "ArrowLeft")).toBe(4);
  });
  it("todas as 5 tabs são alcançáveis por setas a partir da primeira", () => {
    const visited = new Set<number>();
    let i = 0;
    for (let step = 0; step < 5; step++) {
      visited.add(i);
      i = rovingNextIndex(i, 5, "ArrowRight");
    }
    expect(visited.size).toBe(5);
  });
  it("Home/End vão para as extremidades", () => {
    expect(rovingNextIndex(3, 5, "Home")).toBe(0);
    expect(rovingNextIndex(1, 5, "End")).toBe(4);
  });
  it("tecla irrelevante mantém o índice", () => {
    expect(rovingNextIndex(2, 5, "Enter")).toBe(2);
  });
});
