/**
 * Invariantes CSS da fatia visual segura da Agenda e Minha Célula. O jsdom
 * não calcula layout/cascata, então estes contratos leem o CSS-fonte.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "globals.css"), "utf8");
const dashboard = readFileSync(
  join(__dirname, "../components/dashboard/DashboardScreen.tsx"),
  "utf8",
);
const cssWithoutComments = globals.replace(/\/\*[\s\S]*?\*\//g, "");
const cssRules = [...cssWithoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
  selectors: match[1]!.split(",").map((selector) => selector.trim()),
  body: match[2]!,
}));

function bodiesFor(selector: string): string[] {
  return cssRules
    .filter((candidate) => candidate.selectors.includes(selector))
    .map((candidate) => candidate.body);
}

function bodyFor(selector: string, declaration?: string): string {
  const matches = bodiesFor(selector);
  const match = declaration
    ? matches.find((body) => body.includes(declaration))
    : matches[0];
  expect(match, `regra não encontrada: ${selector}`).toBeTruthy();
  return match!;
}

describe("Agenda — gutter e foco operacional", () => {
  it(".agenda-section cria gutter interno de 12px sem recriar card", () => {
    const body = bodyFor(".agenda-section");
    expect(body).toContain("padding: var(--s3) var(--s3) 0");
    expect(body).not.toMatch(/background|border-radius|box-shadow/);
  });

  it.each([
    [".agenda .cal-cell:focus-visible", "-2px"],
    [".agenda .cal-ev:focus-visible", "-2px"],
    [".agenda .agenda-day:focus-visible", "2px"],
    [".agenda .agenda-month:focus-visible", "2px"],
    ['.agenda .agenda-section .list-row[role="button"]:focus-visible', "2px"],
    [".agenda .agenda-row-action:focus-visible", "2px"],
  ])("%s usa o focus-ring com offset adequado", (selector, offset) => {
    const body = bodyFor(selector);
    expect(body).toContain("outline: 2px solid var(--focus-ring)");
    expect(body).toContain(`outline-offset: ${offset}`);
  });
});

describe("Minha Célula — gutter comum sem caixas novas", () => {
  it.each([
    ".mc--member .mc-area:not(.mc-area--meeting) .card",
    ".mc--leader .mc-leader-stack > .card",
  ])("%s usa o gutter comum de 12px", (selector) => {
    expect(bodyFor(selector, "padding-inline")).toContain("padding-inline: var(--s3)");
  });

  it("reunião do membro e seletor de relatório do líder ficam fora do gutter de feeds", () => {
    expect(bodiesFor(".mc--member .mc-area:not(.mc-area--meeting) .card")).not.toHaveLength(0);
    expect(bodiesFor(".mc--leader .mc-leader-stack > .card")).not.toHaveLength(0);
    expect(bodiesFor(".mc--leader .mc-report-picker")).not.toHaveLength(0);
    expect(
      bodiesFor(".mc--leader .mc-report-picker").some((body) => body.includes("padding-inline")),
    ).toBe(false);
  });
});

describe("tipografia operacional — piso de 12px nesta onda", () => {
  it.each([
    ".ddl",
    ".cal-head > div",
    ".agenda .cal-head > div",
    ".agenda .cal-ev",
    ".cal-m-count",
    ".agenda-month-head .count",
    ".agenda-month-list li",
    ".agenda-month-empty",
    ".mc .notice-time",
    ".mc-hero-stat .k",
  ])("%s não fica abaixo de 12px", (selector) => {
    const match = bodyFor(selector, "font-size").match(/font-size:\s*([\d.]+)px/);
    expect(match, `font-size em px não encontrado: ${selector}`).not.toBeNull();
    expect(Number(match![1])).toBeGreaterThanOrEqual(12);
  });
});

describe("fundação sistêmica — superfícies e carregamento", () => {
  it("mantém superfícies planas e separa a tela pelo cabeçalho, não por sombra", () => {
    expect(bodyFor(".card", "background: var(--surface)")).not.toContain("box-shadow");
    const screenHead = bodyFor(".screen-head", "border-bottom");
    expect(screenHead).toContain("border-bottom: 1px solid var(--border-subtle)");
    expect(screenHead).toContain("padding-bottom: var(--s4)");
  });

  it("usa skeleton estático e reduz o gutter horizontal no telefone", () => {
    expect(bodyFor(".screen-loading-line", "background: var(--surface-panel)")).not.toContain(
      "animation",
    );
    expect(globals).toContain("padding-inline: var(--s4)");
  });
});

describe("Agenda e Conversas — composição operacional", () => {
  const agenda = readFileSync(
    join(__dirname, "../components/calendario/CalendarioScreen.tsx"),
    "utf8",
  );
  const inbox = readFileSync(join(__dirname, "../components/inbox/InboxScreen.tsx"), "utf8");

  it("mantém a agenda como um workspace único abaixo do cabeçalho", () => {
    expect(agenda).toContain('className="agenda-workspace"');
    expect(bodyFor(".agenda-workspace > .ds-tabs-wrap > .ds-tabpanel", "padding-top")).toContain(
      "padding-top: var(--s5)",
    );
    expect(bodyFor(".agenda .cal", "border-radius: var(--radius-panel)")).not.toContain(
      "box-shadow",
    );
  });

  it("explica o propósito das conversas antes da lista de atendimento", () => {
    expect(inbox).toContain("Atendimentos pelo WhatsApp");
    expect(inbox).toContain("Converse, assuma ou encaminhe cada cuidado no momento certo.");
    expect(bodyFor(".ib .ib-head", "align-items: flex-end")).toContain(
      "align-items: flex-end",
    );
  });
});

describe("Farol de Hoje — hierarquia visual sem rail persistente", () => {
  it("mantém a fila em uma superfície única e leva o contexto para depois", () => {
    expect(bodyFor(".dh-grid", "display: block")).toContain("display: block");
    expect(bodyFor(".dh-workboard")).toContain("background: var(--surface-raised)");
    expect(bodyFor(".dh-support", "margin-top: var(--s5)")).toContain(
      "margin-top: var(--s5)",
    );
    expect(dashboard).not.toContain('className="dh-side"');
    expect(dashboard.indexOf('className="dh-main dh-workboard"')).toBeLessThan(
      dashboard.indexOf('className="dh-support"'),
    );
  });

  it("eleva ações e filtros desktop ao alvo interno de 40px", () => {
    expect(bodyFor(".dh-filter-btn", "min-height: 40px")).toContain(
      "min-height: 40px",
    );
    expect(bodyFor(".dh-item-actions .ds-btn", "min-height: 40px")).toContain(
      "min-height: 40px",
    );
  });

  it("preserva Quiet Operations sem elevação ou eyebrows repetidos", () => {
    for (const selector of [".dh-hero", ".dh-workboard", ".dh-panel"]) {
      expect(bodyFor(selector, "background: var(--surface-raised)")).not.toContain(
        "box-shadow",
      );
    }
    expect(globals).not.toContain("--dh-panel-shadow");
    expect(globals).not.toContain(".dh-panel-kicker");
    expect(dashboard).not.toContain("dh-panel-kicker");
  });

  it("usa a marca canônica e a escala tipográfica de produto", () => {
    expect(dashboard).toContain('import { DiamondMark } from "@/components/brand/DiamondMark"');
    expect(dashboard).toContain('<DiamondMark className="dh-hero-mark" size={42} title="" />');
    expect(dashboard).not.toContain("dh-hero-facet");
    expect(bodyFor(".dh-title", "font: var(--type-h1)")).toContain(
      "font: var(--type-h1)",
    );
    expect(bodyFor(".dh-queue-title", "font: 650 18px")).toContain(
      "font: 650 18px/1.3 var(--font-display)",
    );
    expect(bodyFor(".dh-item-title", "font: 700 14px")).toContain(
      "font: 700 14px/1.4 var(--font)",
    );
  });

  it("reorganiza o farol e as ações antes de comprimir a fila no tablet", () => {
    const dashboardResponsiveStart = globals.indexOf(".dh-team-workload .dh-person-row");
    const tabletStart = globals.indexOf(
      "@media (max-width: 1100px)",
      dashboardResponsiveStart,
    );
    const mobileStart = globals.indexOf("@media (max-width: 860px)", tabletStart);
    const tabletRules = globals.slice(tabletStart, mobileStart);

    expect(tabletStart).toBeGreaterThanOrEqual(0);
    expect(mobileStart).toBeGreaterThan(tabletStart);
    expect(tabletRules).toContain(".dh-hero-actions");
    expect(tabletRules).toContain("grid-column: 1 / -1");
    expect(tabletRules).toContain(".dh-item-actions");
    expect(tabletRules).toContain("width: 100%");
  });

  it("mantém todos os controles do Dashboard com ao menos 44px no tablet", () => {
    const dashboardResponsiveStart = globals.indexOf(".dh-team-workload .dh-person-row");
    const tabletStart = globals.indexOf(
      "@media (max-width: 860px)",
      dashboardResponsiveStart,
    );
    const mobileStart = globals.indexOf("@media (max-width: 560px)", tabletStart);
    const tabletRules = globals.slice(tabletStart, mobileStart);

    expect(tabletRules).toContain(".dh-hero-actions .ds-btn");
    expect(tabletRules).toContain(".dh-item-actions .ds-btn");
    expect(tabletRules).toContain(".dh-filter-btn");
    expect(tabletRules).toContain("min-height: 44px");
  });

  it("usa caminho G12 explícito e skeleton estático dentro do dashboard", () => {
    expect(bodyFor(".dh-journey-track")).toContain(
      "grid-template-columns: repeat(4",
    );
    expect(bodyFor(".dh .sk-line", "background-color")).toContain(
      "background-color: var(--surface-panel)",
    );
    expect(dashboard).not.toContain("dh-journey-bar");
  });
});
