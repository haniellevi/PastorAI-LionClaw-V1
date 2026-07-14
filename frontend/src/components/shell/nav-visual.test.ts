/**
 * M7B-Visual-W1 (realinhamento estrutural da navegação) — invariantes de CSS
 * que não dá pra provar em jsdom (sem cascata/layout real): regressão por
 * leitura do CSS-fonte, no mesmo padrão de design-tokens.test.ts.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "../../app/globals.css"), "utf8");

function rule(selectorRegexSource: string): string {
  const m = globals.match(new RegExp(`${selectorRegexSource}\\s*\\{([^}]*)\\}`));
  expect(m, `regra não encontrada: ${selectorRegexSource}`).not.toBeNull();
  return m![1]!;
}

describe("nav-item ativo — sem caixa dentro de caixa (Gate 6 / M7B-Visual-W1)", () => {
  it(".nav-item.active não redeclara background no .nav-ic (uma affordance só, não duas aninhadas)", () => {
    expect(globals).not.toMatch(/\.nav-item\.active\s+\.nav-ic\s*\{/);
  });

  it(".nav-item.active continua com UMA affordance própria (tint da linha)", () => {
    const body = rule(String.raw`\.nav-item\.active`);
    expect(body).toContain("background");
  });
});

describe("tooltip do colapsado — visível no hover E no foco de teclado", () => {
  it("[data-tip]::after dispara em :hover e em :focus-visible", () => {
    expect(globals).toMatch(
      /\.sidebar\.collapsed \[data-tip\]:hover::after,\s*\n\s*\.sidebar\.collapsed \[data-tip\]:focus-visible::after\s*\{/,
    );
  });

  it("nav-scroll libera o overflow enquanto o item com tooltip está em hover/foco (senão o tooltip nunca aparece, cortado pelo overflow-x:hidden do scroll)", () => {
    expect(globals).toMatch(
      /\.sidebar\.collapsed \.nav-scroll:has\(\[data-tip\]:hover, \[data-tip\]:focus-visible\)\s*\{\s*overflow:\s*visible;\s*\}/,
    );
  });
});

describe("topbar — título trunca em vez de quebrar linha ou sobrepor busca/chips", () => {
  it(".topbar h1 trunca com reticências (nowrap + ellipsis) em largura estreita", () => {
    const body = rule(String.raw`\.topbar h1`);
    expect(body).toContain("white-space: nowrap");
    expect(body).toContain("text-overflow: ellipsis");
    expect(body).toContain("min-width: 0");
  });
});

describe("bottom-nav — área de toque mínima de 44px (F3 mobile-first)", () => {
  it(".bn-item declara min-height >= 44px", () => {
    const body = rule(String.raw`\.bn-item`);
    const match = body.match(/min-height:\s*(\d+)px/);
    expect(match, "min-height não declarado em .bn-item").not.toBeNull();
    expect(Number(match![1])).toBeGreaterThanOrEqual(44);
  });
});
