/**
 * A fundação importa depois do globals.css. Os dois arquivos não redeclaram os
 * mesmos nomes: globals mantém aliases compatíveis e a fundação guarda os
 * tokens canônicos da identidade Diamante Lapidado.
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

  it("--border-strong legado aponta para a borda azul canônica", () => {
    expect(globals).toMatch(/--border-strong:\s*var\(--border-emphasis\)/);
    expect(rootTokenNames(foundation).has("--border-strong")).toBe(false);
    expect(rootTokenNames(foundation).has("--border-emphasis")).toBe(true);
  });

  it("aliases de marca apontam para a fundação azul", () => {
    expect(globals).toMatch(/--bg:\s*var\(--surface-canvas\)/);
    expect(globals).toMatch(/--accent:\s*var\(--action-primary\)/);
    expect(globals).toMatch(/--sidebar:\s*var\(--diamond-950\)/);
    expect(globals).toMatch(/--grad-brand:\s*var\(--action-primary\)/);
  });

  it("superfícies de marca não reintroduzem a antiga paleta verde", () => {
    const criticalSurfaces = [
      globals,
      read("../components/legal/legal-document.module.css"),
      read("../../public/icon.svg"),
      read("../../public/icon-maskable.svg"),
      read("../../public/brand/diamante-silhueta-16.svg"),
    ].join("\n");
    expect(criticalSurfaces).not.toMatch(
      /#(?:0d9488|0f766e|0f3a36|0b2c29|082220|14b8a6|2dd4bf|5eead4|99f6e4)/i,
    );
  });

  it("favicon aponta para a microversão canônica do Diamante", () => {
    const layout = read("layout.tsx");
    expect(layout).toContain('/brand/diamante-silhueta-16.svg');
    expect(layout).not.toMatch(/icon:\s*["']\/icon\.svg/);
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
