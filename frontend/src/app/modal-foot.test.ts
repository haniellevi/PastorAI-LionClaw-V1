/**
 * PR212-CORRECTIVE-4 (3º finding P2 do Codex) — invariantes de CSS do rodapé de
 * diálogo, que não dá pra provar em jsdom (sem cascata/layout real): regressão
 * por leitura do CSS-fonte, no mesmo padrão de design-tokens.test.ts e
 * nav-visual.test.ts.
 *
 * O VIS-2 pôs `white-space: nowrap` no `.btn`, então o min-content de cada
 * botão passou a ser o rótulo inteiro. Numa linha flex SEM wrap e com
 * `justify-content: flex-end`, o excesso vaza pela ESQUERDA (não entra em
 * scrollWidth): em 360px o "Fechar" do TrackModal saía do rodapé e, com
 * "Confirmar: Visitas de consolidação", do próprio diálogo. A trava é o
 * `flex-wrap: wrap` — e ele só protege enquanto o `nowrap` do `.btn` existir
 * junto, por isso os dois são verificados aqui.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "globals.css"), "utf8");

/** Corpo da PRIMEIRA regra que casa com o seletor. */
function rule(selectorRegexSource: string): string {
  const m = globals.match(new RegExp(`${selectorRegexSource}\\s*\\{([^}]*)\\}`));
  expect(m, `regra não encontrada: ${selectorRegexSource}`).not.toBeNull();
  return m![1]!;
}

describe(".modal-foot — botões quebram de linha em vez de vazar do diálogo", () => {
  const body = rule(String.raw`\.modal-foot`);

  it("declara flex-wrap: wrap (sem isso o botão vaza à esquerda em telas estreitas)", () => {
    expect(body).toMatch(/flex-wrap:\s*wrap/);
  });

  it("continua flex alinhado à direita — a correção não muda o alinhamento", () => {
    expect(body).toMatch(/display:\s*flex/);
    expect(body).toMatch(/justify-content:\s*flex-end/);
  });

  it("preserva o gap entre os botões (vale também entre linhas, após o wrap)", () => {
    expect(body).toMatch(/gap:\s*8px/);
  });

  it("não usa flex-wrap: nowrap nem wrap-reverse (inverteria a ordem visual)", () => {
    expect(body).not.toMatch(/flex-wrap:\s*(nowrap|wrap-reverse)/);
  });

  it("o .btn mantém white-space: nowrap — o wrap é do rodapé, o texto não quebra", () => {
    expect(rule(String.raw`\n\.btn`)).toMatch(/white-space:\s*nowrap/);
  });

  it("o alvo de toque de 44px do rodapé no mobile segue declarado", () => {
    expect(globals).toMatch(/\.modal-foot \.btn\s*\{\s*min-height:\s*44px/);
  });
});
