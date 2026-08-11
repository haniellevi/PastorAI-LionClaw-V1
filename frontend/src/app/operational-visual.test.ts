/**
 * Invariantes CSS da fatia visual segura da Agenda e Minha Célula. O jsdom
 * não calcula layout/cascata, então estes contratos leem o CSS-fonte.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "globals.css"), "utf8");
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
