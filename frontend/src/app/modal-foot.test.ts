/**
 * PR212-CORRECTIVE-4/5/8 (findings P2 do Codex) — invariantes de CSS dos
 * rodapés de diálogo, que não dá pra provar em jsdom (sem cascata/layout real):
 * regressão por leitura do CSS-fonte, no mesmo padrão de design-tokens.test.ts
 * e nav-visual.test.ts.
 *
 * História: o VIS-2 pôs `white-space: nowrap` GLOBAL no `.btn`/`.ds-btn`; o
 * min-content de cada botão virou o rótulo inteiro e linhas flex sem wrap
 * passaram a vazar pela ESQUERDA (overflow que não entra em `scrollWidth`).
 * Casos reais medidos: TrackModal (`.modal-foot`, 360px), ContactPanel
 * (`.ds-dialog-foot`, 320px), CalendarConnectCard e WhatsappScreen (flex
 * inline). O CORRECTIVE-8 inverteu a direção: a BASE deixou de ter nowrap
 * (rótulo pode quebrar dentro do botão em linhas sem wrap) e o nowrap é
 * reaplicado SÓ nos quatro grupos com `flex-wrap: wrap`, onde o botão inteiro
 * desce de linha. Os dois lados do contrato são verificados aqui.
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

describe("nowrap escopado — a base quebra dentro do botão; os grupos com wrap não", () => {
  it(".btn base NÃO tem white-space: nowrap (rótulo pode quebrar em linhas sem wrap)", () => {
    expect(rule(globals, String.raw`\n\.btn`)).not.toMatch(/white-space:\s*nowrap/);
  });

  it(".ds-btn base NÃO tem white-space: nowrap", () => {
    expect(rule(ds, String.raw`\n\.ds-btn`)).not.toMatch(/white-space:\s*nowrap/);
  });

  it("nowrap reaplicado aos botões dos grupos de globals.css protegidos por wrap", () => {
    // Uma regra única cobre .modal-foot (.btn/.ds-btn), .dh-modal-foot
    // (.ds-btn) e .cell-detail-actions (.btn) — as classes reais usadas lá.
    const m = globals.match(
      /\.modal-foot \.btn,\s*\.modal-foot \.ds-btn,\s*\.dh-modal-foot \.ds-btn,\s*\.cell-detail-actions \.btn\s*\{([^}]*)\}/,
    );
    expect(m, "regra escopada de nowrap não encontrada em globals.css").not.toBeNull();
    expect(m![1]).toMatch(/white-space:\s*nowrap/);
  });

  it("nowrap reaplicado aos botões do .ds-dialog-foot (ds.css)", () => {
    const m = ds.match(/\.ds-dialog-foot \.ds-btn,\s*\.ds-dialog-foot \.btn\s*\{([^}]*)\}/);
    expect(m, "regra escopada de nowrap não encontrada em ds.css").not.toBeNull();
    expect(m![1]).toMatch(/white-space:\s*nowrap/);
  });

  it("nowrap fica escopado aos grupos com wrap da Agenda e Minha Célula", () => {
    const selectors = [
      ".agenda .screen-head .actions .btn",
      ".agenda .screen-head .actions .ds-btn",
      ".mc .screen-head .actions .btn",
      ".mc .screen-head .actions .ds-btn",
      ".mc .meeting-actions .btn",
      ".mc .meeting-actions .ds-btn",
      ".mc .chip-actions .btn",
      ".mc .chip-actions .ds-btn",
    ];
    const scopedRule = [...globals.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(
      ([, header, body]) =>
        selectors.every((selector) => header!.includes(selector)) &&
        /white-space:\s*nowrap/.test(body!),
    );
    expect(scopedRule, "regra de nowrap escopada da Agenda/Minha Célula não encontrada").toBeTruthy();
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
    // O seletor aparece em mais de uma regra (nowrap escopado, 44px mobile);
    // basta que ALGUMA declare flex: 1.
    const corpos = [...globals.matchAll(/\.cell-detail-actions \.btn[^{]*\{([^}]*)\}/g)].map(
      (m) => m[1]!,
    );
    expect(corpos.length).toBeGreaterThan(0);
    expect(corpos.some((c) => /flex:\s*1/.test(c))).toBe(true);
  });
});
