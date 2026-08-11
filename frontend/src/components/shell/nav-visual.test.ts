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

describe("tooltip do colapsado — visível no hover E no foco de teclado, sem mexer no scroll (revisão externa achados #1)", () => {
  it("[data-tip]::after (só .side-church, fora do .nav-scroll) dispara em :hover e em :focus-visible", () => {
    expect(globals).toMatch(
      /\.sidebar\.collapsed \[data-tip\]:hover::after,\s*\n\s*\.sidebar\.collapsed \[data-tip\]:focus-visible::after\s*\{/,
    );
  });

  it("NÃO existe mais escape de overflow via :has() no .nav-scroll (regressão do blocker: overflow-x/overflow-y misto no mesmo elemento não dá pra escapar só num eixo — a correção usa o flyout .nav-tip, fora do .nav-scroll)", () => {
    expect(globals).not.toMatch(/\.nav-scroll:has\(/);
  });

  it(".nav-scroll mantém overflow-y:auto INCONDICIONAL (nunca alternado em runtime — nada toca scrollTop/scroll container)", () => {
    const body = rule(String.raw`\.nav-scroll`);
    expect(body).toContain("overflow-y: auto");
    expect(body).toContain("overflow-x: hidden");
  });

  it(".nav-tip (flyout JS-driven, Sidebar.tsx) existe, é decorativo e não intercepta clique", () => {
    const body = rule(String.raw`\.nav-tip`);
    expect(body).toContain("position: absolute");
    expect(body).toContain("pointer-events: none");
  });
});

describe("topbar — título trunca em vez de quebrar linha ou sobrepor os papéis", () => {
  it(".topbar h1 trunca com reticências (nowrap + ellipsis) em largura estreita", () => {
    const body = rule(String.raw`\.topbar h1`);
    expect(body).toContain("white-space: nowrap");
    expect(body).toContain("text-overflow: ellipsis");
    expect(body).toContain("min-width: 0");
  });

  it("os papéis permanecem alinhados à direita depois da remoção da busca decorativa", () => {
    expect(rule(String.raw`\.topbar \.who`)).toContain("margin-left: auto");
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
