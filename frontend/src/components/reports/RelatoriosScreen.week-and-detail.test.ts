// @vitest-environment jsdom
/**
 * Os dois P2 da segunda revisão da PR #221.
 *
 * P2-1 — semana do Histórico: a aba "Semana atual" não manda `?semana=` (quem
 * resolve é o backend, em São Paulo). O Histórico derivava a semana pelo fuso do
 * NAVEGADOR, então na virada da semana ISO as duas abas pediam a MESMA semana.
 *
 * P2-2 — modal aberto: o polling trocava só o array `reports`, enquanto o modal
 * guardava uma cópia congelada do `ReportItem`. A lista atrás virava
 * Atrasado/Recebido e o modal seguia Pendente até fechar e reabrir.
 *
 * Relógio e requisições controlados na mão; o instante é fixado com
 * `setSystemTime`, então nada depende do fuso nem da data da máquina.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Page } from "@/lib/dashboard-api";
import type { ReportItem } from "@/lib/reports-api";

// Objeto ESTÁVEL entre renders (senão o useCallback da carga invalida a cada
// render e o efeito entra em laço infinito).
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

/** Instante do finding: domingo 02/08 21:30 em São Paulo; segunda 03/08 em UTC. */
const VIRADA = new Date("2026-08-03T00:30:00Z");

// ---- fixtures ---------------------------------------------------------------
const PENDENTE: ReportItem = {
  id: "r-1",
  celulaId: "c-1",
  celulaNome: "Célula Zoe",
  semana: "2026-W31",
  status: "pendente",
  dataReuniao: "2026-07-29",
  presentes: null,
  visitantes: null,
  decisoes: null,
  oferta: null,
  observacoes: null,
};

/** MESMO id, agora entregue pelo líder — é o que o poll traz. */
const RECEBIDO: ReportItem = {
  ...PENDENTE,
  status: "recebido",
  presentes: 12,
  visitantes: 3,
  decisoes: 2,
  oferta: 150.5,
  observacoes: "Noite excelente.",
};

function page(items: ReportItem[]): Page<ReportItem> {
  return { items, page: 1, pageSize: 200, total: items.length };
}

// ---- requisições controladas ------------------------------------------------
let pending: Array<{ semana: string | undefined; resolve: (p: Page<ReportItem>) => void }>;

async function resolveRequest(index: number, p: Page<ReportItem>) {
  const alvo = pending[index];
  if (!alvo) throw new Error(`não há requisição em voo na posição ${index}`);
  pending.splice(index, 1);
  await act(async () => {
    alvo.resolve(p);
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // jsdom não implementa layout: offsetParent nulo quebra o filtro de
  // visibilidade do getFocusable usado pelo DsDialog.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement;
    },
  });
  vi.useFakeTimers();
  vi.setSystemTime(VIRADA);
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

/** Abre o modal pelo botão "Ver" da fila de pendentes. */
function clickVerPendente() {
  const btn = container.querySelector<HTMLButtonElement>(".list-row button");
  if (!btn) throw new Error('botão "Ver" da fila de pendentes não encontrado');
  act(() => {
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function dialog(): HTMLElement | null {
  return container.querySelector<HTMLElement>('[role="dialog"]');
}

function dialogText(): string {
  const el = dialog();
  if (!el) throw new Error("modal não está aberto");
  return el.textContent ?? "";
}

// ===========================================================================
// P2-1 — semana do Histórico em America/Sao_Paulo
// ===========================================================================
describe("P2-1 — Histórico deriva a semana no fuso do produto", () => {
  it("em 2026-08-03T00:30Z pede 2026-W30, e a semana atual fica com o backend", async () => {
    render();

    // Semana atual: SEM parâmetro — o backend resolve (responderia 2026-W31).
    expect(pending).toHaveLength(1);
    expect(pending[0]?.semana).toBeUndefined();
    await resolveRequest(0, page([PENDENTE]));

    clickTab("Histórico");
    expect(pending).toHaveLength(1);
    // Pelo fuso do navegador daria 2026-W31 (a MESMA da aba atual). Em São
    // Paulo ainda é domingo 02/08, então o histórico é a W30.
    expect(pending[0]?.semana).toBe("2026-W30");
    expect(apiMock.fetchReports).toHaveBeenLastCalledWith("tok-1", "2026-W30");
  });
});

// ===========================================================================
// P2-2 — modal aberto acompanha o polling
// ===========================================================================
describe("P2-2 — o modal aberto acompanha o refresh", () => {
  it("Pendente -> Recebido com os dados novos, sem fechar e reabrir", async () => {
    render();
    await resolveRequest(0, page([PENDENTE]));

    clickVerPendente();
    expect(dialog()).not.toBeNull();
    expect(dialogText()).toContain("Pendente");
    expect(dialogText()).toContain("Relatório ainda não enviado.");
    expect(dialogText()).not.toContain("Presentes");

    // O poll traz a MESMA reunião, agora enviada.
    await advance(60_000);
    await resolveRequest(0, page([RECEBIDO]));

    // O modal continua aberto e passou a mostrar o consolidado.
    expect(dialog()).not.toBeNull();
    const texto = dialogText();
    expect(texto).toContain("Recebido");
    expect(texto).toContain("Presentes");
    expect(texto).toContain("12");
    expect(texto).toContain("Noite excelente.");
    expect(texto).not.toContain("Relatório ainda não enviado.");
  });

  it("reunião que some do resultado fecha o modal com segurança", async () => {
    render();
    await resolveRequest(0, page([PENDENTE]));
    clickVerPendente();
    expect(dialog()).not.toBeNull();

    // Reunião cancelada / fora da semana: o poll volta sem ela.
    await advance(60_000);
    await resolveRequest(0, page([]));
    expect(dialog()).toBeNull();

    // E não reabre sozinha se um poll futuro trouxer a reunião de volta.
    await advance(60_000);
    await resolveRequest(0, page([RECEBIDO]));
    expect(dialog()).toBeNull();
  });

  it("fechar pelo botão Fechar continua funcionando", async () => {
    render();
    await resolveRequest(0, page([PENDENTE]));
    clickVerPendente();
    expect(dialog()).not.toBeNull();

    const fechar = container.querySelector<HTMLElement>('[aria-label="Fechar"]');
    if (!fechar) throw new Error("botão Fechar não encontrado");
    act(() => {
      fechar.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dialog()).toBeNull();
  });

  it("fechar por Esc e por backdrop continua funcionando", async () => {
    render();
    await resolveRequest(0, page([PENDENTE]));

    clickVerPendente();
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(dialog()).toBeNull();

    clickVerPendente();
    const overlay = container.querySelector<HTMLElement>(".ds-overlay");
    if (!overlay) throw new Error("overlay não encontrado");
    act(() => {
      overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(dialog()).toBeNull();
  });
});
