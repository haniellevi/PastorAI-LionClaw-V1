/**
 * Invariantes CSS da fatia visual segura da Agenda e Minha Célula. O jsdom
 * não calcula layout/cascata, então estes contratos leem o CSS-fonte.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const globals = readFileSync(join(__dirname, "globals.css"), "utf8");
const tokens = readFileSync(join(__dirname, "design-tokens.css"), "utf8");
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

describe("Pessoas, células e Jornada — foco antes de densidade", () => {
  const ganhar = readFileSync(join(__dirname, "../components/contacts/GanharScreen.tsx"), "utf8");
  const contatos = readFileSync(join(__dirname, "../components/contacts/ContatosScreen.tsx"), "utf8");
  const celulas = readFileSync(join(__dirname, "../components/cells/CelulasScreen.tsx"), "utf8");
  const g12 = readFileSync(join(__dirname, "../components/g12/G12Screen.tsx"), "utf8");
  const central = readFileSync(
    join(__dirname, "../components/central-celula/CentralCelulaScreen.tsx"),
    "utf8",
  );

  it("explica a finalidade de cada área antes das listas e dos números", () => {
    expect(ganhar).toContain("Organize novos contatos e visitantes antes do próximo passo da jornada.");
    expect(contatos).toContain("Encontre, atualize e acompanhe cada pessoa com clareza.");
    expect(celulas).toContain("Veja saúde, liderança e vínculos de cada célula.");
    expect(g12).toContain("Navegue pela descendência e pelos indicadores da liderança.");
  });

  it("mantém a Central como workspace único e usa superfícies sem elevação", () => {
    expect(central).toContain('className="cc-workspace"');
    expect(globals).toMatch(
      /\.cc-workspace > \.ds-tabs-wrap > \.ds-tabpanel\s*\{\s*padding-top: var\(--s5\);/,
    );
    expect(bodyFor(".cell-card:hover", "background: var(--surface-2)")).not.toContain(
      "box-shadow",
    );
    expect(bodyFor(".slot.has-team:hover", "background: var(--selection-soft)")).not.toContain(
      "box-shadow",
    );
  });

  it("compacta a escala de números operacionais sem sacrificar a hierarquia", () => {
    expect(bodyFor(".stat .val", "font-size: 26px")).toContain("font-size: 26px");
    expect(bodyFor(".central-card .cc-val", "font-size: 24px")).toContain("font-size: 24px");
    expect(tokens).toContain("--type-h1: 700 24px/1.2 var(--font-display)");
    expect(tokens).toContain("--type-h2: 650 19px/1.3 var(--font-display)");
  });
});

describe("Administração e operação — contexto antes de configuração", () => {
  const setup = readFileSync(join(__dirname, "../components/config/SetupChecklistScreen.tsx"), "utf8");
  const equipe = readFileSync(join(__dirname, "../components/config/EquipeScreen.tsx"), "utf8");
  const permissoes = readFileSync(join(__dirname, "../components/config/PermissoesScreen.tsx"), "utf8");
  const agente = readFileSync(join(__dirname, "../components/config/AgenteScreen.tsx"), "utf8");
  const whatsapp = readFileSync(join(__dirname, "../components/whatsapp/WhatsappScreen.tsx"), "utf8");
  const comunicados = readFileSync(join(__dirname, "../components/comunicados/ComunicadosScreen.tsx"), "utf8");

  it("explica cada decisão administrativa antes dos controles", () => {
    expect(setup).toContain("Conclua o que libera a operação da sua igreja com segurança.");
    expect(equipe).toContain("Convide pessoas e mantenha os papéis necessários para o cuidado da igreja.");
    expect(permissoes).toContain("Defina o que cada responsabilidade pode acessar no painel.");
    expect(agente).toContain("Revise comportamento, credencial e rotinas do agente com contexto.");
    expect(whatsapp).toContain("Conecte e acompanhe o canal usado no cuidado e na comunicação da igreja.");
    expect(comunicados).toContain("Prepare o comunicado, revise o alcance e envie no momento certo.");
  });

  it("mantém matrizes, cards e etapas administrativas em superfícies calmas", () => {
    expect(bodyFor(".admin-screen .card", "background: var(--surface-raised)")).toContain(
      "box-shadow: none",
    );
    expect(bodyFor(".admin-screen .perm-wrap", "border: 1px solid var(--border-subtle)")).toContain(
      "border-radius: var(--radius-control)",
    );
    expect(bodyFor(".operations-screen .bc-steps", "background: var(--surface-panel)")).toContain(
      "border-radius: var(--radius-control)",
    );
  });

  it("preserva alvos de toque e opções responsivas nas telas administrativas", () => {
    const mobileStart = globals.indexOf("@media (max-width: 860px)", globals.indexOf("Administração e operação"));
    const rules = globals.slice(mobileStart, globals.indexOf("GATE 7.2", mobileStart));
    expect(rules).toContain(".admin-screen .btn");
    expect(rules).toContain("min-height: 44px");
    expect(rules).toContain(".admin-screen .role-pick");
    expect(rules).toContain("grid-template-columns: 1fr");
  });
});

describe("Estados de borda — informação antes de frustração", () => {
  const locked = readFileSync(join(__dirname, "../components/consolidacao/LockedScreen.tsx"), "utf8");
  const denied = readFileSync(join(__dirname, "../components/consolidacao/AccessDenied.tsx"), "utf8");
  const screenView = readFileSync(join(__dirname, "../components/shell/ScreenView.tsx"), "utf8");

  it("usa a mesma superfície calma para bloqueio, acesso restrito e áreas futuras", () => {
    expect(locked).toContain('className="screen journey-screen locked-screen"');
    expect(denied).toContain('className="screen journey-screen access-screen"');
    expect(screenView).toContain('className="screen scaffold-screen"');
    expect(bodyFor(".access-screen .card", "background: var(--surface-raised)")).toContain(
      "box-shadow: none",
    );
  });

  it("troca linguagem técnica de sprint por uma orientação clara", () => {
    expect(screenView).toContain("Esta área está sendo preparada");
    expect(screenView).toContain("O conteúdo operacional chega em");
    expect(screenView).not.toContain("Casca pronta — conteúdo na próxima sprint");
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
