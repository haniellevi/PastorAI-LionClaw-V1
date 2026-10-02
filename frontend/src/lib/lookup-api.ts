import { authedFetch, ApiError, type Page } from "./dashboard-api";
import type { Contact, ContactView } from "./contacts-api";
import type { CellSummary } from "./cells-api";

export type ContactLookup = Pick<Contact,
  "id" | "nome" | "telefone" | "email" | "tipo" | "celulaId" |
  "liderDeCelula" | "aptoLider" | "semInteresse" | "arquivada">;
export type CellLookup = Pick<CellSummary, "id" | "nome" | "liderId" | "ativo">;
export interface LookupParams {
  q?: string;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
}

function paramsQuery({ q = "", page = 1, pageSize = 25 }: LookupParams) {
  const query = new URLSearchParams({
    page: String(Math.max(1, Math.trunc(page))),
    pageSize: String(Math.min(200, Math.max(1, Math.trunc(pageSize)))),
  });
  if (q.trim()) query.set("q", q.trim().slice(0, 120));
  return query;
}

const searchKey = (value: string) => value.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase("pt-BR");

async function readLegacyPages<T extends { id: string }>(
  token: string, route: string, extra: Record<string, string> = {}, signal?: AbortSignal,
): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  let expectedTotal: number | undefined;
  for (let page = 1; ; page += 1) {
    const query = new URLSearchParams({ page: String(page), pageSize: "200", ...extra });
    const response = await authedFetch(token, `${route}?${query}`, { signal });
    if (!response.ok) throw new ApiError(response.status, "Não foi possível carregar as opções.");
    const batch = await response.json() as Page<T>;
    if (batch.page !== page || !Number.isSafeInteger(batch.total) || batch.total < 0 ||
      (expectedTotal !== undefined && batch.total !== expectedTotal)) {
      throw new ApiError(502, "A paginação recebida está inconsistente. Tente novamente.");
    }
    expectedTotal = batch.total;
    for (const item of batch.items) {
      if (seen.has(item.id)) throw new ApiError(502, "A paginação recebida está inconsistente. Tente novamente.");
      seen.add(item.id);
      items.push(item);
    }
    if (items.length === expectedTotal) return items;
    if (items.length > expectedTotal || batch.items.length === 0) {
      throw new ApiError(502, "A lista recebida está incompleta. Tente novamente.");
    }
  }
}

/** Only an absent route permits legacy reads. Authorization failures propagate. */
async function lookupPage<T extends { id: string; nome: string }>(
  token: string, route: string, params: LookupParams,
  extra: Record<string, string> = {},
  matches: (item: T, q: string) => boolean = (item, q) => searchKey(item.nome).includes(q),
): Promise<Page<T>> {
  const query = paramsQuery(params);
  for (const [key, value] of Object.entries(extra)) query.set(key, value);
  const response = await authedFetch(token, `${route}/lookup?${query}`, { signal: params.signal });
  if (response.ok) return await response.json() as Page<T>;
  if (response.status !== 404) throw new ApiError(response.status, "Não foi possível carregar as opções.");

  // Older backends ignore q. Read their real pages before applying search,
  // otherwise a person after row 200 would remain unreachable.
  const items = await readLegacyPages<T>(token, route, extra, params.signal);
  const q = searchKey(params.q?.trim() ?? "");
  const scoped = extra.celulaId ? items.filter((item) => "celulaId" in item && item.celulaId === extra.celulaId) : items;
  const filtered = q ? scoped.filter((item) => matches(item, q)) : scoped;
  const resultPage = Number(query.get("page"));
  const pageSize = Number(query.get("pageSize"));
  return { items: filtered.slice((resultPage - 1) * pageSize, resultPage * pageSize),
    total: filtered.length, page: resultPage, pageSize };
}

export function fetchCellLookupPage(token: string, params: LookupParams = {}): Promise<Page<CellLookup>> {
  return lookupPage(token, "/cells", params);
}

export function fetchContactLookupPage(
  token: string, params: LookupParams & { view?: ContactView; celulaId?: string } = {},
): Promise<Page<ContactLookup>> {
  return lookupPage<ContactLookup>(token, "/contacts", params, { view: params.view ?? "all", ...(params.celulaId ? { celulaId: params.celulaId } : {}) },
    (item, q) => searchKey(`${item.nome} ${item.telefone} ${item.email ?? ""}`).includes(q));
}

export async function fetchCellListPage(token: string, params: LookupParams = {}): Promise<Page<CellSummary>> {
  if (params.q?.trim()) {
    const probe = await authedFetch(token, `/cells/lookup?${paramsQuery(params)}`, { signal: params.signal });
    if (probe.status === 404) {
      // Force the compatibility reader, whose rows include the full cell data.
      return lookupPage<CellSummary>(token, "/cells", params);
    }
    if (!probe.ok) throw new ApiError(probe.status, "Não foi possível carregar as células.");
  }
  const response = await authedFetch(token, `/cells?${paramsQuery(params)}`, { signal: params.signal });
  if (!response.ok) throw new ApiError(response.status, "Não foi possível carregar as células.");
  return await response.json() as Page<CellSummary>;
}

export interface CellStats {
  total: number; ativas: number; semLider: number; pessoasEmCelulas: number;
  /** Complete legacy snapshot used only to restore the visible card labels/counts. */
  legacyCells?: CellSummary[];
}
export async function fetchCellStats(token: string, signal?: AbortSignal): Promise<CellStats> {
  const response = await authedFetch(token, "/cells/summary", { signal });
  if (response.status === 404) {
    const [cells, people] = await Promise.all([
      readLegacyPages<CellSummary>(token, "/cells", {}, signal),
      readLegacyPages<ContactLookup>(token, "/contacts", { view: "all" }, signal),
    ]);
    const names = new Map(people.map((person) => [person.id, person.nome]));
    const counts = new Map<string, { membros: number; visitantes: number }>();
    for (const person of people) {
      if (!person.celulaId) continue;
      const count = counts.get(person.celulaId) ?? { membros: 0, visitantes: 0 };
      if (person.tipo === "visitante") count.visitantes += 1;
      else count.membros += 1;
      counts.set(person.celulaId, count);
    }
    return {
      total: cells.length,
      ativas: cells.filter((cell) => cell.ativo).length,
      semLider: cells.filter((cell) => !cell.liderId).length,
      pessoasEmCelulas: people.filter((person) => !!person.celulaId).length,
      legacyCells: cells.map((cell) => ({ ...cell,
        liderNome: cell.liderId ? names.get(cell.liderId) ?? null : null,
        ...(counts.get(cell.id) ?? { membros: 0, visitantes: 0 }),
      })),
    };
  }
  if (!response.ok) throw new ApiError(response.status, "Não foi possível carregar os indicadores de células.");
  return await response.json() as CellStats;
}
