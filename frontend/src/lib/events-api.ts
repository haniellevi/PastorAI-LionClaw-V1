/**
 * Cliente da API de eventos / Google Calendar (tela #calendario).
 * Consome o backend (sprint-009):
 *
 *   GET  /events                          -> Page<EventItem>  (RNF-09)
 *   POST /events {titulo,data,hora,descricao} -> EventItem     (api-events)
 *
 * Sync com o Google Calendar é best-effort: o evento é sempre persistido. Se o
 * sync falha (token expirado/serviço fora), o evento volta com
 * `sincronizado=false` e `googleEventId=null` — a UI mantém o evento local e o
 * marca como "não sincronizado" com re-tentar. Vários eventos não sincronizados
 * sinalizam o calendário desconectado (banner com CTA reconectar).
 */

import { ApiError, authedFetch, readDetail, type Page } from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Evento da igreja (EventOut). */
export interface EventItem {
  id: string;
  // EVT-1: `data` é nullable — eventos com recorrencia='semanal' não têm data
  // fixa (espelha events.data, que deixou de ser NOT NULL). A UI trata data=null
  // como "recorrente" (seção própria), nunca como dia do grid.
  titulo: string;
  data: string | null; // YYYY-MM-DD | null
  hora: string | null;
  descricao: string | null;
  googleEventId: string | null;
  sincronizado: boolean;
  // EVT-2 (aditivo): estado da Agenda. Opcionais — eventos antigos podem omitir.
  status?: string | null;
  origem?: string | null;
  recorrencia?: string | null;
  confirmadoEm?: string | null;
  confirmadoPor?: string | null;
}

export interface CreateEventInput {
  titulo: string;
  data: string; // YYYY-MM-DD
  hora?: string | null;
  descricao?: string | null;
}

// EVT-4: edição parcial. O backend (PUT /events/{id}) trata campos None como
// "inalterados" — não dá pra zerar hora/descrição por aqui (limitação aceita;
// sem mudança de backend nesta fase).
export interface UpdateEventInput {
  titulo?: string;
  data?: string; // YYYY-MM-DD
  hora?: string | null;
  descricao?: string | null;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchEvents(token: string, pageSize = 200): Promise<Page<EventItem>> {
  const res = await authedFetch(token, `/events?page=1&pageSize=${pageSize}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a agenda.");
  }
  return (await res.json()) as Page<EventItem>;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
export async function createEvent(
  token: string,
  input: CreateEventInput,
): Promise<EventItem> {
  const res = await authedFetch(token, `/events`, {
    method: "POST",
    body: JSON.stringify({
      titulo: input.titulo,
      data: input.data,
      hora: input.hora ?? null,
      descricao: input.descricao ?? null,
    }),
  });
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à agenda da igreja.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar o evento.");
  }
  return (await res.json()) as EventItem;
}

/** EVT-4: edição parcial de um evento (PUT /events/{id}). */
export async function updateEvent(
  token: string,
  id: string,
  input: UpdateEventInput,
): Promise<EventItem> {
  const res = await authedFetch(token, `/events/${id}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à agenda da igreja.");
  }
  if (res.status === 404) {
    throw new ApiError(404, "Evento não encontrado.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar as alterações.");
  }
  return (await res.json()) as EventItem;
}

/** EVT-4: exclusão de um evento (DELETE /events/{id}). 404 é tratado como idempotente. */
export async function deleteEvent(token: string, id: string): Promise<void> {
  const res = await authedFetch(token, `/events/${id}`, { method: "DELETE" });
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à agenda da igreja.");
  }
  if (res.status === 404) return; // já não existe — remoção é idempotente
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível excluir o evento.");
  }
}

/** EVT-4: confirmação manual de um evento 'a_confirmar' (POST /events/{id}/confirm). */
export async function confirmEvent(token: string, id: string): Promise<EventItem> {
  const res = await authedFetch(token, `/events/${id}/confirm`, { method: "POST" });
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à agenda da igreja.");
  }
  if (res.status === 404) {
    throw new ApiError(404, "Evento não encontrado.");
  }
  if (res.status === 409) {
    throw new ApiError(409, "Este evento não está aguardando confirmação.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível confirmar o evento.");
  }
  return (await res.json()) as EventItem;
}

// ---------------------------------------------------------------------------
// Derivações de UI (visões Semana / Mês / Ano — EVT-3)
//
// Tudo aqui é puro e baseado em string "YYYY-MM-DD" para a comparação de datas:
// `new Date("2026-06-29")` é UTC-meia-noite e desloca o dia em fusos negativos,
// então NUNCA comparamos eventos via Date — só por prefixo/igualdade de string.
// As datas do "cursor" (navegação) usam Date local, e isoDate() as serializa.
// ---------------------------------------------------------------------------
export type EventView = "semana" | "mes" | "ano";

export interface CalendarCell {
  /** Dia do mês (1..N) ou null para preenchimento fora do mês. */
  day: number | null;
  iso: string | null;
  today: boolean;
  events: EventItem[];
}

/** Dia da visão Semana (lista vertical de 7 dias). */
export interface DayCell {
  iso: string;
  weekday: number; // 0 = domingo
  day: number;
  monthShort: string;
  today: boolean;
  events: EventItem[];
}

/** Mês resumido da visão Ano. */
export interface MonthSummary {
  month: number; // 0..11
  label: string;
  count: number;
  events: EventItem[];
  isCurrent: boolean;
}

const MONTH_NAMES = [
  "Janeiro",
  "Fevereiro",
  "Março",
  "Abril",
  "Maio",
  "Junho",
  "Julho",
  "Agosto",
  "Setembro",
  "Outubro",
  "Novembro",
  "Dezembro",
];

const MONTH_SHORT = [
  "jan", "fev", "mar", "abr", "mai", "jun",
  "jul", "ago", "set", "out", "nov", "dez",
];

export function monthLabel(year: number, month: number): string {
  return `${MONTH_NAMES[month]} ${year}`;
}

function isoDate(year: number, month: number, day: number): string {
  const mm = String(month + 1).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

/** Date local (00:00) a partir de "YYYY-MM-DD", sem deslocar por fuso. */
export function dateFromIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

/** "YYYY-MM-DD" → "29 de junho de 2026" (string-based, sem Date/fuso). EVT-4. */
export function formatLongDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const name = MONTH_NAMES[(m ?? 1) - 1]?.toLowerCase() ?? "";
  return `${d} de ${name} de ${y}`;
}

/** Ordena por hora ("HH:MM"); sem hora (dia inteiro) vem primeiro. */
function byHora(a: EventItem, b: EventItem): number {
  if (a.hora === b.hora) return 0;
  if (a.hora == null) return -1;
  if (b.hora == null) return 1;
  return a.hora < b.hora ? -1 : 1;
}

/** Ordena por data e depois hora (visão Ano). */
function byDataHora(a: EventItem, b: EventItem): number {
  if (a.data !== b.data) return (a.data ?? "") < (b.data ?? "") ? -1 : 1;
  return byHora(a, b);
}

/** Indexa eventos COM data por "YYYY-MM-DD" (recorrentes/sem data são ignorados). */
function groupByDate(events: EventItem[]): Map<string, EventItem[]> {
  const byDay = new Map<string, EventItem[]>();
  for (const ev of events) {
    if (ev.data == null) continue;
    const list = byDay.get(ev.data);
    if (list) list.push(ev);
    else byDay.set(ev.data, [ev]);
  }
  return byDay;
}

/**
 * Separa eventos com data fixa dos recorrentes (data=null ⇒ recorrencia
 * 'semanal', EVT-1). `dia_semana` não é exposto no EventOut, então recorrentes
 * não podem ser posicionados num dia do grid — vão para uma seção própria.
 */
export function partitionEvents(events: EventItem[]): {
  dated: EventItem[];
  recurring: EventItem[];
} {
  const dated: EventItem[] = [];
  const recurring: EventItem[] = [];
  for (const e of events) (e.data == null ? recurring : dated).push(e);
  return { dated, recurring };
}

/** Constrói as células do mês (semana começando no domingo, como o artifact). */
export function buildMonthGrid(
  year: number,
  month: number,
  events: EventItem[],
  now: Date = new Date(),
): CalendarCell[] {
  const byDay = groupByDate(events);
  const firstDow = new Date(year, month, 1).getDay(); // 0 = domingo
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayIso = isoDate(now.getFullYear(), now.getMonth(), now.getDate());

  const cells: CalendarCell[] = [];
  for (let i = 0; i < firstDow; i += 1) {
    cells.push({ day: null, iso: null, today: false, events: [] });
  }
  for (let d = 1; d <= daysInMonth; d += 1) {
    const iso = isoDate(year, month, d);
    cells.push({
      day: d,
      iso,
      today: iso === todayIso,
      events: (byDay.get(iso) ?? []).slice().sort(byHora),
    });
  }
  return cells;
}

/** Eventos do mês corrente (filtra a lista bruta por ano/mês). */
export function eventsInMonth(events: EventItem[], year: number, month: number): EventItem[] {
  const prefix = `${year}-${String(month + 1).padStart(2, "0")}-`;
  return events.filter((e) => e.data != null && e.data.startsWith(prefix));
}

/** Domingo (00:00 local) da semana que contém `d`. */
function startOfWeek(d: Date): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - x.getDay());
  return x;
}

/** Os 7 dias (Dom→Sáb) da semana que contém `cursor`, com eventos por dia. */
export function buildWeekDays(
  cursor: Date,
  events: EventItem[],
  now: Date = new Date(),
): DayCell[] {
  const byDay = groupByDate(events);
  const todayIso = isoDate(now.getFullYear(), now.getMonth(), now.getDate());
  const start = startOfWeek(cursor);
  const cells: DayCell[] = [];
  for (let i = 0; i < 7; i += 1) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const iso = isoDate(d.getFullYear(), d.getMonth(), d.getDate());
    cells.push({
      iso,
      weekday: d.getDay(),
      day: d.getDate(),
      monthShort: MONTH_SHORT[d.getMonth()] ?? "",
      today: iso === todayIso,
      events: (byDay.get(iso) ?? []).slice().sort(byHora),
    });
  }
  return cells;
}

/** Os 12 meses do ano `year`, cada um com contagem + eventos resumidos. */
export function buildYearMonths(
  year: number,
  events: EventItem[],
  now: Date = new Date(),
): MonthSummary[] {
  const buckets: EventItem[][] = Array.from({ length: 12 }, () => []);
  const prefix = `${year}-`;
  for (const e of events) {
    if (e.data == null || !e.data.startsWith(prefix)) continue;
    const mi = Number(e.data.slice(5, 7)) - 1;
    const bucket = buckets[mi];
    if (bucket) bucket.push(e);
  }
  const curYear = now.getFullYear();
  const curMonth = now.getMonth();
  return buckets.map((evs, m) => ({
    month: m,
    label: MONTH_NAMES[m] ?? "",
    count: evs.length,
    events: evs.sort(byDataHora),
    isCurrent: year === curYear && m === curMonth,
  }));
}

/** Avança/retrocede o cursor pela unidade da visão atual. */
export function shiftCursor(cursor: Date, view: EventView, dir: number): Date {
  const y = cursor.getFullYear();
  const m = cursor.getMonth();
  const d = cursor.getDate();
  if (view === "semana") return new Date(y, m, d + 7 * dir);
  if (view === "ano") return new Date(y + dir, m, 1);
  return new Date(y, m + dir, 1); // mes
}

/** Rótulo do período em foco, conforme a visão. */
export function viewLabel(cursor: Date, view: EventView): string {
  if (view === "ano") return String(cursor.getFullYear());
  if (view === "mes") return monthLabel(cursor.getFullYear(), cursor.getMonth());
  const start = startOfWeek(cursor);
  const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6);
  if (start.getMonth() === end.getMonth()) {
    return `${start.getDate()}–${end.getDate()} ${MONTH_SHORT[start.getMonth()]} ${start.getFullYear()}`;
  }
  return `${start.getDate()} ${MONTH_SHORT[start.getMonth()]} – ${end.getDate()} ${MONTH_SHORT[end.getMonth()]} ${end.getFullYear()}`;
}
