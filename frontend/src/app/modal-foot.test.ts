/**
 * PR212-CORRECTIVE-4/5 (3º e 4º findings P2 do Codex) — invariantes de CSS dos
 * rodapés de diálogo, que não dá pra provar em jsdom (sem cascata/layout real):
 * regressão por leitura do CSS-fonte, no mesmo padrão de design-tokens.test.ts
 * e nav-visual.test.ts.
 *
 * O VIS-2 pôs `white-space: nowrap` no `.btn` (e a fundação já tinha no
 * `.ds-btn`), então o min-content de cada botão passou a ser o rótulo inteiro.
 * Num rodapé flex SEM wrap e com `justify-content: flex-end`, o excesso vaza
 * pela ESQUERDA — e overflow à esquerda NÃO entra em `scrollWidth`, por isso o
 * defeito passava batido. Casos reais medidos: "Fechar" + "Confirmar: Visitas
 * de consolidação" (TrackModal, `.modal-foot`) saía do próprio diálogo em
 * 360px; "Cancelar" + "Reativar comunicações" (ContactPanel,
 * `.ds-dialog-foot`) em 320px.
 *
 * A trava é `flex-wrap: wrap` nos TRÊS rodapés de ação da base — e ela só
 * protege enquanto o `nowrap` dos botões existir junto, por isso os dois lados
 * são verificados aqui.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "globals.css"), "utf8");
const ds = readFileSync(join(__dirname, "ds.css"), "utf8");

/** Corpo da PRIMEIRA regra que casa com o seletor, no CSS informado. */
function rule(css: string, selectorRegexSource: string): string {
  const m = css.match(new RegExp(`${selectorRegexSource}\\s*\\{([^}]*)\\}`));
  expect(m, `regra não encontrada: ${selectorRegexSource}`).not.toBeNull();
  return m![1]!;
}

/** Os três rodapés de ação da base: mesmo defeito, mesma trava. */
const RODAPES = [
  { nome: ".modal-foot", css: globals, sel: String.raw`\.modal-foot` },
  { nome: ".ds-dialog-foot", css: ds, sel: String.raw`\.ds-dialog-foot` },
  { nome: ".dh-modal-foot", css: globals, sel: String.raw`\.dh-modal-foot` },
] as const;

describe.each(RODAPES)("$nome — botões quebram de linha em vez de vazar do diálogo", ({ css, sel }) => {
  it("declara flex-wrap: wrap (sem isso o botão vaza à esquerda em telas estreitas)", () => {
    expect(rule(css, sel)).toMatch(/flex-wrap:\s*wrap/);
  });

  it("continua flex alinhado à direita — a correção não muda o alinhamento", () => {
    const body = rule(css, sel);
    expect(body).toMatch(/display:\s*flex/);
    expect(body).toMatch(/justify-content:\s*flex-end/);
  });

  it("não usa nowrap nem wrap-reverse no contêiner (inverteria a ordem visual)", () => {
    expect(rule(css, sel)).not.toMatch(/flex-wrap:\s*(nowrap|wrap-reverse)/);
  });

  it("preserva o espaçamento entre os botões (vale também entre linhas, após o wrap)", () => {
    expect(rule(css, sel)).toMatch(/gap:\s*(8px|var\(--s2\))/);
  });
});

describe("rodapés de diálogo — o wrap é do contêiner, o texto do botão não quebra", () => {
  it(".btn mantém white-space: nowrap", () => {
    expect(rule(globals, String.raw`\n\.btn`)).toMatch(/white-space:\s*nowrap/);
  });

  it(".ds-btn mantém white-space: nowrap", () => {
    expect(rule(ds, String.raw`\n\.ds-btn`)).toMatch(/white-space:\s*nowrap/);
  });

  it("o alvo de toque de 44px do .modal-foot no mobile segue declarado", () => {
    expect(globals).toMatch(/\.modal-foot \.btn\s*\{\s*min-height:\s*44px/);
  });

  // A varredura repo-wide que existia aqui (todo `display:flex` +
  // `justify-content:flex-end` sem `flex-wrap` reprovava) foi removida a pedido
  // da revisão externa: nem todo flex alinhado à direita é um rodapé de ações —
  // uma toolbar de linha fixa futura falharia a suíte mesmo estando correta.
  // A cobertura fica nos testes parametrizados dos três rodapés acima.
});

/**
 * PR212-CORRECTIVE-7 (finding P2 do Codex): as ações do detalhe da célula
 * ("Editar célula" + "Convidar membro", CelulasScreen) eram um flex inline SEM
 * wrap com dois botões `flex: 1` — com o `.btn` em `white-space: nowrap`, a
 * soma dos min-content passava da largura do card no celular e os controles
 * vazavam. Mesma classe de defeito dos rodapés acima, mesma trava.
 */
describe(".cell-detail-actions — par de ações do detalhe da célula quebra de linha", () => {
  const body = rule(globals, String.raw`\.cell-detail-actions`);

  it("declara flex + flex-wrap: wrap (linha única quando cabe; botão inteiro desce quando não)", () => {
    expect(body).toMatch(/display:\s*flex/);
    expect(body).toMatch(/flex-wrap:\s*wrap/);
    expect(body).not.toMatch(/flex-wrap:\s*(nowrap|wrap-reverse)/);
  });

  it("preserva gap e respiro do grupo", () => {
    expect(body).toMatch(/gap:\s*var\(--s2\)/);
    expect(body).toMatch(/margin-bottom:\s*var\(--s4\)/);
  });

  it("os botões seguem flexíveis (dividem a linha quando lado a lado)", () => {
    expect(rule(globals, String.raw`\.cell-detail-actions \.btn`)).toMatch(/flex:\s*1/);
  });
});
