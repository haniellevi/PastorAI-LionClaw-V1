// @vitest-environment jsdom
/**
 * Relógio do produto — P2 da terceira revisão da PR #221.
 *
 * O polling era gateado por `tab === "atual"`, então o Histórico ficava
 * congelado em dois eixos ao mesmo tempo: (a) a semana explícita era calculada
 * uma vez e nunca mais, de modo que a aba aberta na virada de segunda em São
 * Paulo continuava na semana que era histórica ANTES da meia-noite; e (b) o
 * status não era rebuscado, então a reunião de domingo à noite cujo SLA de 2h
 * vence depois da meia-noite seguia exibida como Pendente.
 *
 * A correção é um ÚNICO relógio: o tick move o instante, a semana é recalculada
 * na renderização e só então a busca é refeita — nas duas abas.
 *
 * Instantes absolutos + fake timers: nada aqui depende do fuso nem da data da
 * máquina. Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Page } from "@/lib/dashboard-api";
import type { ReportItem } from "@/lib/reports-api";

const auth = vi.hoisted(() => ({
  token: "tok-1",
  user: { roles: ["pastor"] as string[], appUserId: "u-1" },
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));

const apiMock = vi.hoisted(() => ({ fetchReports: vi.fn() }));

vi.mock("@/lib/reports-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reports-api")>();
  return { ...actual, fetchReports: apiMock.fetchReports };
});

const { RelatoriosScreen } = await import("./RelatoriosScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Domingo 02/08/2026, 23:59:30 em São Paulo (= 03/08 02:59:30Z).
 * Nesse instante a semana corrente é a 2026-W31 e a histórica é a 2026-W30.
 * 30s depois vira segunda 03/08 (W32) e a histórica passa a ser a 2026-W31.
 */
const DOMINGO_23_59_30 = new Date("2026-08-03T02:59:30Z");

/** Reunião de domingo 02/08 às 23:00 — SLA de 2h vence às 01:00 de segunda. */
function reuniaoDomingo(status: "pendente" | "atrasado"): ReportItem {
  return {
    id: "r-dom",
    celulaId: "c-1",
    celulaNome: "Célula Zoe",
    semana: "2026-W31",
    status,
    dataReuniao: "2026-08-02",
    presentes: null,
    visitantes: null,
    decisoes: null,
    oferta: null,
    observacoes: null,
  };
}

function page(items: ReportItem[]): Page<ReportItem> {
  return { items, page: 1, pageSize: 200, total: items.length };
}

let pending: Array<{ semana: string | undefined; resolve: (p: Page<ReportItem>) => void }>;

async function resolveRequest(index: number, p: Page<ReportItem>) {
  const alvo = pending[index];
  if (!alvo) throw new Error(`não há requisição em voo na posição ${index}`);
  pending.splice(index, 1);
  await act(async () => {
    alvo.resolve(p);
  });
}

/** Avança o relógio real E o fake, para `Date.now()` acompanhar os timers. */
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(DOMINGO_23_59_30);
  pending = [];
  apiMock.fetchReports.mockReset();
  apiMock.fetchReports.mockImplementation(
    (_token: string, semana?: string) =>
      new Promise<Page<ReportItem>>((resolve) => {
        pending.push({ semana, resolve });
      }),
  );
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function render() {
  act(() => {
    root.render(h(RelatoriosScreen));
  });
}

function clickTab(label: string) {
  const btn = Array.from(container.querySelectorAll("button")).find(
    (b) => b.textContent?.trim() === label,
  );
  if (!btn) throw new Error(`aba "${label}" não encontrada`);
  act(() => {
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function pillText(): string {
  const pill = container.querySelector(".list-row .pill");
  if (!pill) throw new Error("status-pill não encontrada");
  return pill.textContent ?? "";
}

describe("relógio do produto — Histórico atravessa a virada de semana", () => {
  it("antes da meia-noite pede 2026-W30; depois passa a pedir 2026-W31", async () => {
    render();
    await resolveRequest(0, page([])); // semana atual

    // 23:59:30 de domingo: a semana histórica ainda é a W30.
    clickTab("Histórico");
    expect(pending[0]?.semana).toBe("2026-W30");
    await resolveRequest(0, page([]));

    // Um tick de 60s atravessa a meia-noite: agora é segunda 03/08 (W32) e a
    // semana recém-encerrada — a histórica — é a W31.
    await advance(60_000);
    expect(pending).toHaveLength(1);
    expect(pending[0]?.semana).toBe("2026-W31");
  });

  it("SLA de reunião de domingo vence depois da meia-noite e a pílula migra", async () => {
    render();
    await resolveRequest(0, page([]));

    clickTab("Histórico");
    expect(pending[0]?.semana).toBe("2026-W30");
    await resolveRequest(0, page([]));

    // Vira para segunda: o histórico passa a ser a W31, que contém a reunião de
    // domingo 23:00 — o backend ainda a classifica como pendente (SLA às 01:00).
    await advance(60_000);
    expect(pending[0]?.semana).toBe("2026-W31");
    await resolveRequest(0, page([reuniaoDomingo("pendente")]));
    expect(pillText()).toBe("Pendente");

    // Ticks seguintes: passada 01:00, o backend devolve atrasado e a tela
    // acompanha — sem recarregar e sem sair da aba Histórico.
    await advance(60_000);
    expect(pending).toHaveLength(1);
    await resolveRequest(0, page([reuniaoDomingo("atrasado")]));
    expect(pillText()).toBe("Atrasado");
  });

  it("Semana atual continua sem parâmetro e refaz a busca no tick", async () => {
    render();
    expect(pending[0]?.semana).toBeUndefined();
    await resolveRequest(0, page([reuniaoDomingo("pendente")]));
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(2);
    expect(pending[0]?.semana).toBeUndefined();
    await resolveRequest(0, page([reuniaoDomingo("atrasado")]));
    expect(pillText()).toBe("Atrasado");
  });

  it("o refresh do tick é silencioso: sem skeleton e sem apagar a tela", async () => {
    render();
    await resolveRequest(0, page([reuniaoDomingo("pendente")]));

    await advance(60_000);
    // Requisição em voo: os dados anteriores continuam visíveis.
    expect(container.querySelector(".skeleton")).toBeNull();
    expect(container.textContent).toContain("Célula Zoe");
    await resolveRequest(0, page([reuniaoDomingo("atrasado")]));
    expect(container.querySelector(".skeleton")).toBeNull();
  });

  it("desmontar cancela o único relógio", async () => {
    render();
    await resolveRequest(0, page([]));
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    act(() => root.unmount());

    await advance(60_000);
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    root = createRoot(container); // afterEach desmonta de novo
  });
});
