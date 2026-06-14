/**
 * Cliente da API de células (#celulas — F7 / delta-007).
 * Consome os endpoints do backend (sprint-004):
 *
 *   GET  /cells                                  -> Page<CellSummary>
 *   GET  /cells/{id}                             -> CellDetail (com alerts)
 *   POST /cells                                  -> CellSummary  (upsert)
 *   POST /cells/{id}/alerts/{aid}/baixar         -> CellAlert    (tratado=true)
 *
 * Reaproveita o transporte autenticado (authedFetch) e o tratamento de 401
 * do dashboard-api. Editar célula exige líder-ou-superior (403); criar exige
 * papel de liderança pastoral. cobertura_espiritual é obrigatória (422/edge).
 */

import {
  ApiError,
  authedFetch,
  readDetail,
  type Page,
} from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Projeção de célula retornada por /cells (CellOut). */
export interface CellSummary {
  id: string;
  nome: string;
  liderId: string | null;
  diaReuniao: string | null;
  coberturaEspiritual: string;
  ativo: boolean;
}

/** Alerta aberto sobre um liderado da célula (cell_alerts). */
export interface CellAlert {
  id: string;
  pessoaId: string;
  gatilho: string | null;
  acaoEsperada: string | null;
  tratado: boolean;
}

/** Detalhe da célula com seus alertas em aberto. */
export interface CellDetail extends CellSummary {
  alerts: CellAlert[];
}

/** Entrada para criar (sem id) ou editar (com id) uma célula. */
export interface UpsertCellInput {
  id?: string | null;
  nome: string;
  liderId?: string | null;
  diaReuniao?: string | null;
  coberturaEspiritual: string;
  ativo?: boolean;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchCellsFull(
  token: string,
  pageSize = 200,
): Promise<Page<CellSummary>> {
  const res = await authedFetch(token, `/cells?page=1&pageSize=${pageSize}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as células.");
  }
  return (await res.json()) as Page<CellSummary>;
}

export async function fetchCellDetail(
  token: string,
  cellId: string,
): Promise<CellDetail> {
  const res = await authedFetch(token, `/cells/${cellId}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível abrir a célula.");
  }
  return (await res.json()) as CellDetail;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
/**
 * Cria ou edita uma célula. cobertura_espiritual é obrigatória. Editar uma
 * célula existente exige líder-ou-superior na hierarquia (403 com motivo).
 */
export async function upsertCell(
  token: string,
  input: UpsertCellInput,
): Promise<CellSummary> {
  const res = await authedFetch(token, `/cells`, {
    method: "POST",
    body: JSON.stringify({
      id: input.id ?? null,
      nome: input.nome,
      liderId: input.liderId ?? null,
      diaReuniao: input.diaReuniao ?? null,
      coberturaEspiritual: input.coberturaEspiritual,
      ativo: input.ativo ?? true,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar a célula.");
  }
  return (await res.json()) as CellSummary;
}

/** Marca um alerta da célula como tratado (tratado=true). */
export async function baixarAlert(
  token: string,
  cellId: string,
  alertId: string,
): Promise<CellAlert> {
  const res = await authedFetch(
    token,
    `/cells/${cellId}/alerts/${alertId}/baixar`,
    { method: "POST", body: JSON.stringify({}) },
  );
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível tratar o alerta.");
  }
  return (await res.json()) as CellAlert;
}
