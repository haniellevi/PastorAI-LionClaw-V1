/**
 * Cliente da API da Central de Células (dashboard, fila de relatórios, saúde).
 * Consome os endpoints do backend (cell_central.py), todos restritos à Central:
 *
 *   GET /cell-central/dashboard        -> CentralDashboard    (contadores E16)
 *   GET /cell-central/pending-reports  -> PendingReportsPage  (paginado)
 *   GET /cell-central/health           -> CellHealthList      (saúde on-read)
 *
 * Contrato snake_case (`relatorios_pendentes`, `celula_nome`, `lider_nome`).
 * Reaproveita o transporte autenticado (authedFetch) do dashboard-api.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Contadores do painel da Central (DashboardOut / E16). */
export interface CentralDashboard {
  relatorios_pendentes: number;
  solicitacoes_aguardando: number;
  celulas_com_alerta: number;
  multiplicacoes_pendentes: number;
  avisos_recentes: number;
  materiais_recentes: number;
}

/** Item da fila de relatórios pendentes (PendingReportItem). */
export interface PendingReportItem {
  reuniao_id: string;
  celula_id: string;
  celula_nome: string;
  lider_nome: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
}

/** Página de relatórios pendentes (PendingReportsPage). */
export interface PendingReportsPage {
  items: PendingReportItem[];
  page: number;
  page_size: number;
}

/** Sinal de saúde de uma reunião (HealthSignalOut): `cor` verde/vermelho/alerta. */
export interface HealthSignal {
  reuniao_id: string;
  cor: "verde" | "vermelho" | "alerta";
}

/** Saúde de uma célula (CellHealthOut). */
export interface CellHealth {
  celula_id: string;
  celula_nome: string;
  status: string;
  sinais: HealthSignal[];
  vermelhos: number;
  alertas: number;
}

/** Lista de saúde das células (HealthOut) — menos saudáveis primeiro. */
export interface CellHealthList {
  cells: CellHealth[];
}

/** Contadores do painel da Central (E16). */
export async function getDashboard(token: string): Promise<CentralDashboard> {
  const res = await authedFetch(token, `/cell-central/dashboard`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar o painel da central.");
  }
  return (await res.json()) as CentralDashboard;
}

/** Fila paginada de relatórios pendentes (reuniões passadas não canceladas). */
export async function getPendingReports(
  token: string,
  page = 1,
  pageSize = 50,
): Promise<PendingReportsPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await authedFetch(token, `/cell-central/pending-reports?${query.toString()}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os relatórios pendentes.");
  }
  return (await res.json()) as PendingReportsPage;
}

/** Saúde das células (calculada on-read; ordena menos saudáveis primeiro). */
export async function getHealth(
  token: string,
  page = 1,
  pageSize = 50,
): Promise<CellHealthList> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await authedFetch(token, `/cell-central/health?${query.toString()}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar a saúde das células.");
  }
  return (await res.json()) as CellHealthList;
}
