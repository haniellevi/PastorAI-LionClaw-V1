/**
 * Gate 6.1 (P1 — isolamento dos tokens da fundação): design-tokens.css importa
 * DEPOIS do globals.css no layout; qualquer custom property de :root repetida
 * lá sobrescreveria o valor legado em TODAS as telas não migradas (foi o caso
 * de --border-strong). Regressão: os dois :root não podem compartilhar nomes.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const read = (f: string) => readFileSync(join(__dirname, f), "utf8");

/** Nomes de custom properties DECLARADAS nos blocos :root de um CSS. */
function rootTokenNames(css: string): Set<string> {
  const names = new Set<string>();
  for (const block of css.matchAll(/:root\s*{([^}]*)}/g)) {
    for (const decl of block[1]!.matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
      names.add(decl[1]!);
    }
  }
  return names;
}

describe("isolamento de tokens (globals.css × design-tokens.css)", () => {
  const globals = read("globals.css");
  const foundation = read("design-tokens.css");

  it("nenhum token do :root legado é redeclarado no :root da fundação", () => {
    const legacy = rootTokenNames(globals);
    const ds = rootTokenNames(foundation);
    const collisions = [...ds].filter((n) => legacy.has(n));
    expect(collisions).toEqual([]);
  });

  it("--border-strong legado preserva o valor teal e a fundação usa --border-emphasis", () => {
    expect(globals).toMatch(/--border-strong:\s*oklch\(87\.5% 0\.014 181\)/);
    expect(rootTokenNames(foundation).has("--border-strong")).toBe(false);
    expect(rootTokenNames(foundation).has("--border-emphasis")).toBe(true);
  });

  it("sidebar colapsada não usa display:none nos rótulos (nome acessível preservado)", () => {
    // O bloco que esconde .lbl/.nav-group-title na colapsada deve ser o padrão
    // sr-only (clip-path), nunca display:none — senão controles icon-only
    // perdem o nome para leitores de tela (Gate 6.1 P1).
    const block = globals.match(
      /\.sidebar\.collapsed \.lbl,\s*\.sidebar\.collapsed \.nav-group-title\s*{([^}]*)}/,
    );
    expect(block).not.toBeNull();
    expect(block![1]).not.toContain("display: none");
    expect(block![1]).toContain("clip-path");
  });
});
