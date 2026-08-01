// @vitest-environment jsdom
/**
 * P2 da revisão da PR #221 — a tela mantinha "Pendente" depois de a reunião
 * cruzar `data + hora + 2h`.
 *
 * O status pendente/atrasado passou a vir do BACKEND, mas a tela só buscava na
 * carga inicial: com a aba aberta, a pílula congelava no valor da primeira
 * resposta. (A implementação anterior a esta PR recalculava o SLA no cliente a
 * cada 60s; a correção NÃO volta a calcular no cliente — apenas rebusca.)
 *
 * Relógio e requisições controlados na mão: nada resolve sozinho, então a ordem
 * carga-inicial → +60s → segunda resposta é exata e não depende de timing real.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Page } from "@/lib/dashboard-api";
import type { ReportItem } from "@/lib/reports-api";

// Objeto ESTÁVEL entre renders: a tela memoiza `load` a partir de
// `expireSession`; uma referência nova a cada render invalidaria o useCallback
// e o efeito de carga entraria em laço infinito.
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

// ---- fixtures --------------------------------------------------------------
function reuniao(status: "pendente" | "atrasado" | "recebido"): ReportItem {
  return {
    id: "r-1",
    celulaId: "c-1",
    celulaNome: "Célula Zoe",
    semana: "2026-W31",
    status,
    dataReuniao: "2026-07-29",
    presentes: null,
    visitantes: null,
    decisoes: null,
    oferta: null,
    observacoes: null,
  };
}

function page(status: "pendente" | "atrasado" | "recebido"): Page<ReportItem> {
  return { items: [reuniao(status)], page: 1, pageSize: 200, total: 1 };
}

// ---- requisições controladas ------------------------------------------------
/** Requisições em voo, na ordem de disparo. */
let pending: Array<{ semana: string | undefined; resolve: (p: Page<ReportItem>) => void }>;

async function resolveRequest(index: number, p: Page<ReportItem>) {
  const alvo = pending[index];
  if (!alvo) throw new Error(`não há requisição em voo na posição ${index}`);
  pending.splice(index, 1);
  await act(async () => {
    alvo.resolve(p);
  });
}

/** Avança o relógio fake e deixa o React processar o que o timer disparou. */
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
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

function text(): string {
  return container.textContent ?? "";
}

/**
 * Texto da status-pill da linha pendente. Olhamos a pílula, não o texto da
 * tela: o título do painel é "Pendentes", que contém "Pendente" como substring
 * e mascararia a migração do status.
 */
function pillText(): string {
  const pill = container.querySelector(".list-row .pill");
  if (!pill) throw new Error("status-pill não encontrada na fila de pendentes");
  return `${pill.textContent ?? ""} | ${pill.className}`;
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

describe("RelatoriosScreen — refetch na fronteira do SLA (P2 #221)", () => {
  it("migra Pendente -> Atrasado após 60s, sem recarregar a página", async () => {
    render();
    expect(pending).toHaveLength(1);

    // 1. Primeira resposta do servidor: Pendente (pílula warn).
    await resolveRequest(0, page("pendente"));
    expect(pillText()).toBe("Pendente | pill warn");

    // 2. Passam 60s -> a tela dispara um novo fetch sozinha.
    await advance(60_000);
    expect(pending).toHaveLength(1);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(2);

    // 3. A segunda resposta traz Atrasado (o backend cruzou data+hora+2h).
    //    Sem reload: a mesma árvore React trocou a pílula.
    await resolveRequest(0, page("atrasado"));
    expect(pillText()).toBe("Atrasado | pill danger");
    expect(container.querySelector(".list-row")?.className).toContain("overdue");
  });

  it("o refresh em segundo plano não mostra skeleton nem apaga os dados", async () => {
    render();
    await resolveRequest(0, page("pendente"));
    expect(container.querySelector(".skeleton")).toBeNull();
    expect(text()).toContain("Célula Zoe");

    await advance(60_000);
    // Requisição em voo: a tela continua com os dados anteriores na tela.
    expect(pending).toHaveLength(1);
    expect(container.querySelector(".skeleton")).toBeNull();
    expect(text()).toContain("Célula Zoe");
    expect(pillText()).toBe("Pendente | pill warn");

    await resolveRequest(0, page("atrasado"));
    expect(container.querySelector(".skeleton")).toBeNull();
    expect(text()).toContain("Célula Zoe");
  });

  it("não dispara polls concorrentes: ciclo com requisição em voo é pulado", async () => {
    render();
    await resolveRequest(0, page("pendente"));
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    // 1º ciclo dispara e NÃO resolve.
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(2);
    expect(pending).toHaveLength(1);

    // 2º e 3º ciclos com a resposta ainda em voo: nada de novo é disparado.
    await advance(60_000);
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(2);
    expect(pending).toHaveLength(1);

    // Depois que a resposta chega, o ciclo seguinte volta a buscar.
    await resolveRequest(0, page("atrasado"));
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(3);
  });

  it("o Histórico TAMBÉM refresca — dado histórico não é imutável", async () => {
    // Antes o polling era gateado por `tab === "atual"` e o Histórico ficava
    // congelado: nem o SLA da reunião de domingo nem a virada de semana
    // chegavam à tela. O relógio do produto agora vale para as duas abas.
    render();
    await resolveRequest(0, page("pendente"));
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    // Troca de aba: dispara a carga do histórico (semana explícita).
    clickTab("Histórico");
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(2);
    expect(pending[0]?.semana).toMatch(/^\d{4}-W\d{2}$/);
    await resolveRequest(0, page("recebido"));

    // Cada tick refaz a busca também no histórico.
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(3);
    await resolveRequest(0, page("recebido"));
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(4);
    await resolveRequest(0, page("recebido"));

    // E a semana atual segue igual, sem parâmetro.
    clickTab("Semana atual");
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(5);
    expect(pending[0]?.semana).toBeUndefined();
    await resolveRequest(0, page("pendente"));
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(6);
  });

  it("desmontar a tela cancela o polling", async () => {
    render();
    await resolveRequest(0, page("pendente"));
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    act(() => root.unmount());

    await advance(60_000);
    await advance(60_000);
    expect(apiMock.fetchReports).toHaveBeenCalledTimes(1);

    // afterEach desmonta de novo; recria uma raiz vazia para não estourar.
    root = createRoot(container);
  });
});
