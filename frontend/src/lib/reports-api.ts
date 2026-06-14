/**
 * Cliente da API de relatórios de célula (telas #relatorios e #central-celula).
 * Consome o backend (sprint-009):
 *
 *   GET /reports?semana=YYYY-Www -> Page<ReportItem>  (api-reports)
 *
 * Relatórios recebidos vêm da tabela `reports` (status=recebido). Células
 * ativas com líder que ainda não entregaram a semana vêm como entradas
 * sintéticas com id=null e status=pendente (RNF-09), para o painel cobrar quem
 * falta. O prazo de SLA do relatório não trafega no payload — é derivado da
 * própria semana (encerramento no domingo 22h), o que faz a status-pill migrar
 * de warn (pendente) para danger (atrasado) quando o prazo estoura, sem reload.
 *
 * A cobrança automática de relatório atrasado é disparada pelo motor de SLA/cron
 * no backend (sprint-008). O botão "Cobrar" do painel aciona a mesma cobrança de
 * forma manual e otimista — fiel ao artifact travado (toast de confirmação).
 */

import { ApiError, authedFetch, type Page } from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Projeção de relatório (ReportOut). Pendentes sintéticos têm id=null. */
export interface ReportItem {
  id: string | null;
  celulaId: string;
  celulaNome: string | null;
  semana: string;
  status: string; // recebido | pendente
  dataReuniao: string | null;
  presentes: number | null;
  visitantes: number | null;
  decisoes: number | null;
  oferta: number | null;
  observacoes: string | null;
  origem: string | null;
}

export interface ReportSplit {
  recebidos: ReportItem[];
  pendentes: ReportItem[];
}

/** Tom da status-pill de SLA do relatório pendente. */
export type ReportSlaTone = "warn" | "danger";

export interface ReportSlaInfo {
  tone: ReportSlaTone;
  label: string;
  /** true quando o prazo da semana já estourou (warn -> danger). */
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
export function splitReports(items: ReportItem[]): ReportSplit {
  const recebidos: ReportItem[] = [];
  const pendentes: ReportItem[] = [];
  for (const r of items) {
    if (r.status === "pendente") pendentes.push(r);
    else recebidos.push(r);
  }
  return { recebidos, pendentes };
}

/** Segunda-feira (00h local) da semana ISO `YYYY-Www`. */
function isoWeekMonday(semana: string): Date | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(semana.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const week = Number(match[2]);
  if (Number.isNaN(year) || Number.isNaN(week)) return null;
  // 4 de janeiro está sempre na semana ISO 1.
  const jan4 = new Date(year, 0, 4);
  const jan4Dow = (jan4.getDay() + 6) % 7; // 0 = segunda
  const week1Monday = new Date(year, 0, 4 - jan4Dow);
  return new Date(
    week1Monday.getFullYear(),
    week1Monday.getMonth(),
    week1Monday.getDate() + (week - 1) * 7,
  );
}

/**
 * Prazo do relatório semanal: encerramento no domingo da semana às 22h (local).
 * Derivado da semana ISO, pois o payload de pendentes não traz prazo.
 */
export function reportDeadline(semana: string): Date | null {
  const monday = isoWeekMonday(semana);
  if (!monday) return null;
  const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6, 22, 0, 0);
  return sunday;
}

/**
 * Estado de SLA de um relatório pendente. Antes do prazo é `warn` (pendente);
 * depois do prazo vira `danger` (atrasado) — realçando a cobrança na fila.
 */
export function reportSla(item: ReportItem, now: number = Date.now()): ReportSlaInfo {
  const deadline = reportDeadline(item.semana);
  if (deadline && now > deadline.getTime()) {
    return { tone: "danger", label: "Atrasado", overdue: true };
  }
  return { tone: "warn", label: "Pendente", overdue: false };
}
