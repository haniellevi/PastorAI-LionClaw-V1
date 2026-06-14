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
  titulo: string;
  data: string; // YYYY-MM-DD
  hora: string | null;
  descricao: string | null;
  googleEventId: string | null;
  sincronizado: boolean;
}

export interface CreateEventInput {
  titulo: string;
  data: string; // YYYY-MM-DD
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

// ---------------------------------------------------------------------------
// Derivações de UI (calendário mensal)
// ---------------------------------------------------------------------------
export interface CalendarCell {
  /** Dia do mês (1..N) ou null para preenchimento fora do mês. */
  day: number | null;
  iso: string | null;
  today: boolean;
  events: EventItem[];
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

export function monthLabel(year: number, month: number): string {
  return `${MONTH_NAMES[month]} ${year}`;
}

function isoDate(year: number, month: number, day: number): string {
  const mm = String(month + 1).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

/** Constrói as células do mês (semana começando no domingo, como o artifact). */
export function buildMonthGrid(
  year: number,
  month: number,
  events: EventItem[],
  now: Date = new Date(),
): CalendarCell[] {
  const byDay = new Map<string, EventItem[]>();
  for (const ev of events) {
    const list = byDay.get(ev.data);
    if (list) list.push(ev);
    else byDay.set(ev.data, [ev]);
  }

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
      events: byDay.get(iso) ?? [],
    });
  }
  return cells;
}

/** Eventos do mês corrente (filtra a lista bruta por ano/mês). */
export function eventsInMonth(events: EventItem[], year: number, month: number): EventItem[] {
  const prefix = `${year}-${String(month + 1).padStart(2, "0")}-`;
  return events.filter((e) => e.data.startsWith(prefix));
}
