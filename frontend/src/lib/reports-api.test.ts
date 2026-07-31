/**
 * Semana do Histórico derivada em `America/Sao_Paulo` (P2-1 da review 2 da #221).
 *
 * A aba "Semana atual" não manda `?semana=` — quem resolve é o backend, também
 * em São Paulo. Se o Histórico usasse o fuso do NAVEGADOR, na virada da semana
 * ISO as duas abas pediriam a mesma semana: em `2026-08-03T00:30Z` o backend
 * responde `2026-W31` e um navegador em UTC calcularia `2026-W31` para o
 * histórico, em vez de `2026-W30`.
 *
 * Os instantes são passados explicitamente, então nada aqui depende do fuso nem
 * da data da máquina que roda o teste.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "./api";
import { ApiError } from "./dashboard-api";
import { fetchReports, previousIsoWeekInSaoPaulo, splitReports, type ReportItem } from "./reports-api";

describe("previousIsoWeekInSaoPaulo", () => {
  it("na virada da semana ISO usa o dia civil de São Paulo, não o de UTC", () => {
    // 2026-08-03T00:30Z = domingo 02/08 21:30 em São Paulo (fim da W31), mas já
    // segunda 03/08 (W32) em UTC. Derivando pelo calendário UTC o histórico
    // pediria W31 — exatamente a semana que o backend devolve para a aba
    // "Semana atual". Em São Paulo o correto é W30.
    expect(previousIsoWeekInSaoPaulo(new Date("2026-08-03T00:30:00Z"))).toBe("2026-W30");
  });

  it("depois da meia-noite de São Paulo já conta o dia novo", () => {
    // 2026-08-03T03:30Z = segunda 03/08 00:30 em São Paulo (início da W32).
    expect(previousIsoWeekInSaoPaulo(new Date("2026-08-03T03:30:00Z"))).toBe("2026-W31");
  });

  it("meio de semana devolve a semana anterior", () => {
    // Quarta 29/07/2026 (W31) -> anterior = W30.
    expect(previousIsoWeekInSaoPaulo(new Date("2026-07-29T15:00:00Z"))).toBe("2026-W30");
  });

  it("atravessa a virada de ano ISO", () => {
    // 2027-01-07T12:00Z = quinta 07/01/2027, semana ISO 2027-W01 -> anterior
    // é a última semana de 2026 (W53).
    expect(previousIsoWeekInSaoPaulo(new Date("2027-01-07T12:00:00Z"))).toBe("2026-W53");
  });

  it("é estável para o mesmo instante, independente de quantas vezes rodar", () => {
    const instante = new Date("2026-08-03T00:30:00Z");
    expect(previousIsoWeekInSaoPaulo(instante)).toBe(previousIsoWeekInSaoPaulo(instante));
  });
});

// ===========================================================================
// Paginação — o grão virou REUNIÃO, então 200 itens deixaram de bastar
// ===========================================================================
/**
 * Com o grão por célula, 200 itens cobriam qualquer igreja do MVP. Com o grão
 * por REUNIÃO não cobrem: duas reuniões da mesma célula na mesma semana são
 * suportadas de propósito, então uma igreja com bem menos de 200 células pode
 * estourar o teto. Buscar só a página 1 truncava a lista em silêncio — e as
 * contagens e o "Tudo em dia!" saíam de dado incompleto.
 */
const TOKEN = "tok-1";

function reuniao(id: string, status: "pendente" | "recebido" | "atrasado"): ReportItem {
  return {
    id,
    celulaId: `c-${id}`,
    celulaNome: `Célula ${id}`,
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

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Query strings de cada chamada, na ordem em que foram feitas. */
let calls: URLSearchParams[];

function mockPages(pages: Array<{ items: ReportItem[]; total: number } | Response>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://local.test");
    calls.push(url.searchParams);
    const next = pages[calls.length - 1];
    if (next === undefined) throw new Error(`chamada extra inesperada #${calls.length}`);
    if (next instanceof Object && "ok" in next) return next as Response;
    const { items, total } = next as { items: ReportItem[]; total: number };
    return jsonResponse({ items, page: calls.length, pageSize: 200, total });
  }) as typeof fetch;
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  calls = [];
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("fetchReports — busca todas as páginas", () => {
  it("total=201: junta 200 da primeira página com 1 da segunda", async () => {
    const primeira = Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido"));
    const segunda = [reuniao("r-200", "pendente")];
    mockPages([
      { items: primeira, total: 201 },
      { items: segunda, total: 201 },
    ]);

    const page = await fetchReports(TOKEN, "2026-W31");

    expect(page.items).toHaveLength(201);
    expect(page.total).toBe(201);
    expect(page.page).toBe(1);
    expect(page.pageSize).toBe(200);
    expect(calls).toHaveLength(2);
  });

  it("todas as páginas usam a mesma semana e pageSize, variando só page", async () => {
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido")), total: 201 },
      { items: [reuniao("r-200", "pendente")], total: 201 },
    ]);

    await fetchReports(TOKEN, "2026-W31");

    expect(calls.map((q) => q.get("page"))).toEqual(["1", "2"]);
    expect(calls.map((q) => q.get("pageSize"))).toEqual(["200", "200"]);
    expect(calls.map((q) => q.get("semana"))).toEqual(["2026-W31", "2026-W31"]);
  });

  it("sem semana explícita, nenhuma página manda o parâmetro", async () => {
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido")), total: 201 },
      { items: [reuniao("r-200", "pendente")], total: 201 },
    ]);

    await fetchReports(TOKEN);

    expect(calls.map((q) => q.get("semana"))).toEqual([null, null]);
  });

  it("pendente que só existe na 2a página entra no agregado e em splitReports", async () => {
    // Sem paginação a tela mostraria "Tudo em dia!" com uma pendência de fora.
    const primeira = Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido"));
    mockPages([
      { items: primeira, total: 201 },
      { items: [reuniao("r-atrasada", "atrasado")], total: 201 },
    ]);

    const page = await fetchReports(TOKEN, "2026-W31");
    const { recebidos, pendentes } = splitReports(page.items);

    expect(recebidos).toHaveLength(200);
    expect(pendentes).toHaveLength(1);
    expect(pendentes[0]?.id).toBe("r-atrasada");
  });

  it("total <= 200 faz uma única chamada", async () => {
    mockPages([{ items: [reuniao("r-0", "recebido")], total: 1 }]);

    const page = await fetchReports(TOKEN, "2026-W31");

    expect(page.items).toHaveLength(1);
    expect(calls).toHaveLength(1);
  });

  it("não pede página extra depois de alcançar o total", async () => {
    // Exatamente 400 em duas páginas cheias: a 3a chamada seria erro no mock.
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`a-${i}`, "recebido")), total: 400 },
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`b-${i}`, "recebido")), total: 400 },
    ]);

    const page = await fetchReports(TOKEN, "2026-W31");

    expect(page.items).toHaveLength(400);
    expect(calls).toHaveLength(2);
  });

  it("página vazia encerra o laço mesmo com total inconsistente", async () => {
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido")), total: 999 },
      { items: [], total: 999 },
    ]);

    const page = await fetchReports(TOKEN, "2026-W31");

    expect(page.items).toHaveLength(200);
    expect(calls).toHaveLength(2);
  });

  it("falha na 2a página rejeita a leitura inteira, sem resultado parcial", async () => {
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido")), total: 201 },
      jsonResponse({ detail: "erro" }, 500),
    ]);

    await expect(fetchReports(TOKEN, "2026-W31")).rejects.toBeInstanceOf(ApiError);
    expect(calls).toHaveLength(2);
  });

  it("401 numa página posterior preserva o SessionExpiredError", async () => {
    mockPages([
      { items: Array.from({ length: 200 }, (_, i) => reuniao(`r-${i}`, "recebido")), total: 201 },
      jsonResponse({}, 401),
    ]);

    await expect(fetchReports(TOKEN, "2026-W31")).rejects.toBeInstanceOf(SessionExpiredError);
  });
});
