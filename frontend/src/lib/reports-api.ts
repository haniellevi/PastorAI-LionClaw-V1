/**
 * Cliente da API de relatórios de célula (tela #relatorios).
 *
 *   GET /reports?semana=YYYY-Www -> Page<ReportItem>  (api-reports)
 *
 * A fonte de verdade é `celula_reuniao` (+ `relatorio_snapshot`): UM item por
 * REUNIÃO materializada da semana. Célula sem reunião no período não aparece —
 * não existe mais pendência sintética por célula.
 *
 * O SLA NÃO é mais derivado no cliente. O backend classifica cada reunião em
 * `recebido` (relatório enviado), `pendente` (ainda dentro da carência) ou
 * `atrasado` (passou `data + hora + 2h` em America/Sao_Paulo). A regra legada de
 * "domingo 22h" foi removida — ela não correspondia a nenhuma regra do produto.
 *
 * O endpoint é restrito a pastor/admin: a listagem é tenant-wide e carrega
 * oferta e observações de todas as células. O líder lê o relatório da própria
 * célula pelos endpoints de `cell-meetings`.
 */

import { ApiError, authedFetch, type Page } from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Status de um relatório, tal como o backend classifica. */
export type ReportStatus = "recebido" | "pendente" | "atrasado";

/**
 * Projeção de relatório (ReportOut). `id` é o id da REUNIÃO e existe sempre.
 * Números, oferta e observações só vêm preenchidos depois do envio.
 * Não há campo `origem`: o relatório é enviado pelo painel do líder.
 */
export interface ReportItem {
  id: string;
  celulaId: string;
  celulaNome: string | null;
  semana: string;
  status: ReportStatus | string;
  dataReuniao: string;
  presentes: number | null;
  visitantes: number | null;
  decisoes: number | null;
  oferta: number | null;
  observacoes: string | null;
}

export interface ReportSplit {
  recebidos: ReportItem[];
  pendentes: ReportItem[];
}

/** Tom da status-pill de um relatório ainda não enviado. */
export type ReportSlaTone = "warn" | "danger";

export interface ReportSlaInfo {
  tone: ReportSlaTone;
  label: string;
  /** true quando o backend já marcou a reunião como atrasada (SLA de 2h). */
  overdue: boolean;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchReports(
  token: string,
  semana?: string,
  pageSize = 200,
): Promise<Page<ReportItem>> {
  const query = new URLSearchParams({ page: "1", pageSize: String(pageSize) });
  if (semana) query.set("semana", semana);
  const res = await authedFetch(token, `/reports?${query.toString()}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar os relatórios.");
  }
  return (await res.json()) as Page<ReportItem>;
}

// ---------------------------------------------------------------------------
// Derivações de UI
// ---------------------------------------------------------------------------
export function isReceived(item: ReportItem): boolean {
  return item.status === "recebido";
}

export function splitReports(items: ReportItem[]): ReportSplit {
  const recebidos: ReportItem[] = [];
  const pendentes: ReportItem[] = [];
  for (const r of items) {
    if (isReceived(r)) recebidos.push(r);
    else pendentes.push(r);
  }
  return { recebidos, pendentes };
}

/**
 * Estado de SLA de um relatório não enviado, LIDO do status do servidor.
 * `atrasado` (passou data+hora+2h) realça a cobrança; `pendente` é warn.
 */
export function reportSla(item: ReportItem): ReportSlaInfo {
  if (item.status === "atrasado") {
    return { tone: "danger", label: "Atrasado", overdue: true };
  }
  return { tone: "warn", label: "Pendente", overdue: false };
}

/** Data da reunião (`YYYY-MM-DD`) formatada em pt-BR, sem deslocar o fuso. */
export function formatMeetingDate(dataReuniao: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dataReuniao.trim());
  if (!match) return dataReuniao;
  return `${match[3]}/${match[2]}/${match[1]}`;
}

// ---------------------------------------------------------------------------
// Semana ISO no fuso do PRODUTO
// ---------------------------------------------------------------------------
/** Fuso canônico do produto — o mesmo que o backend usa para semana e SLA. */
export const SAO_PAULO_TZ = "America/Sao_Paulo";

/**
 * Data civil (ano/mês/dia) em São Paulo no instante dado.
 *
 * Lê as PARTES numéricas de `Intl.DateTimeFormat` — sem parse de string, que
 * dependeria do locale. O navegador pode estar em qualquer fuso: usar
 * `getFullYear()/getMonth()/getDate()` daria o calendário da máquina, não o do
 * produto (às 00:30Z de 03/08 ainda é dia 02/08 em São Paulo).
 */
function saoPauloCivilDate(now: Date): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: SAO_PAULO_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const pick = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((p) => p.type === type)?.value);
  return { year: pick("year"), month: pick("month"), day: pick("day") };
}

/** Semana ISO `YYYY-Www` de uma data civil (algoritmo ISO-8601, âncora em UTC). */
function isoWeekOfCivilDate(year: number, month: number, day: number): string {
  const date = new Date(Date.UTC(year, month - 1, day));
  const dow = (date.getUTCDay() + 6) % 7; // 0 = segunda
  date.setUTCDate(date.getUTCDate() - dow + 3); // quinta-feira da semana
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const firstDow = (firstThursday.getUTCDay() + 6) % 7;
  const week =
    1 + Math.round((date.getTime() - firstThursday.getTime()) / 86400000 / 7 + (firstDow - 3) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

/**
 * Semana ISO ANTERIOR à corrente, em `America/Sao_Paulo` — o que a aba
 * Histórico consulta.
 *
 * A aba "Semana atual" NÃO manda `?semana=`: quem resolve a semana corrente é o
 * backend (`current_iso_week`, também em São Paulo). Se o histórico derivasse a
 * semana pelo fuso do navegador, as duas abas pediriam a MESMA semana na virada
 * — em `2026-08-03T00:30Z` o backend responde `2026-W31` e um navegador em UTC
 * calcularia `2026-W31` para o histórico em vez de `2026-W30`.
 */
export function previousIsoWeekInSaoPaulo(now: Date = new Date()): string {
  const { year, month, day } = saoPauloCivilDate(now);
  const anchor = new Date(Date.UTC(year, month - 1, day));
  anchor.setUTCDate(anchor.getUTCDate() - 7);
  return isoWeekOfCivilDate(
    anchor.getUTCFullYear(),
    anchor.getUTCMonth() + 1,
    anchor.getUTCDate(),
  );
}
