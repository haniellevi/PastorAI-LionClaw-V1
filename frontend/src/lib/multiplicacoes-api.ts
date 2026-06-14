/**
 * Cliente da API de multiplicações (#enviar — US-21/22/23, delta-027).
 * Consome os endpoints do backend (sprint-005):
 *
 *   GET  /multiplicacoes[?status=<s>]      -> Page<Multiplicacao>
 *   POST /multiplicacoes                   -> Multiplicacao   (agendar)
 *   POST /multiplicacoes/{id}/aprovar      -> ApproveResult   (gate supervisão)
 *
 * delta-027: a aprovação fica bloqueada enquanto supervisao_ok=false; o backend
 * responde 409 {error: "supervision_pending"} e a UI desabilita o botão com o
 * motivo. Reaproveita o transporte autenticado (authedFetch) do dashboard-api.
 */

import {
  ApiError,
  authedFetch,
  isRecord,
  readDetail,
  type Page,
} from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Status do ciclo de multiplicação (multiplicacao_status). */
export type MultiplicacaoStatus =
  | "agendada"
  | "sem_agendamento"
  | "aprovada"
  | "concluida";

/** Projeção de multiplicação retornada por /multiplicacoes (MultiplicacaoOut). */
export interface Multiplicacao {
  id: string;
  celulaId: string;
  status: string | null;
  /** ISO date (YYYY-MM-DD) ou null quando ainda sem agendamento. */
  dataPrevista: string | null;
  descendencia: string | null;
  novoLiderId: string | null;
  supervisaoOk: boolean;
  aprovadaPor: string | null;
}

export interface ScheduleMultiplicacaoInput {
  celulaId: string;
  dataPrevista?: string | null;
  novoLiderId?: string | null;
  descendencia?: string | null;
}

export interface ApproveResult {
  status: string;
  multiplicacaoId: string;
  aprovadaPor: string;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchMultiplicacoes(
  token: string,
  statusFilter?: MultiplicacaoStatus,
  pageSize = 200,
): Promise<Page<Multiplicacao>> {
  const query = new URLSearchParams({ page: "1", pageSize: String(pageSize) });
  if (statusFilter) query.set("status", statusFilter);
  const res = await authedFetch(token, `/multiplicacoes?${query.toString()}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as multiplicações.");
  }
  return (await res.json()) as Page<Multiplicacao>;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
/**
 * Agenda uma multiplicação. Com dataPrevista vira `agendada`; sem data fica
 * `sem_agendamento` (pendência de data destacada na aba correspondente).
 */
export async function scheduleMultiplicacao(
  token: string,
  input: ScheduleMultiplicacaoInput,
): Promise<Multiplicacao> {
  const res = await authedFetch(token, `/multiplicacoes`, {
    method: "POST",
    body: JSON.stringify({
      celulaId: input.celulaId,
      dataPrevista: input.dataPrevista ?? null,
      novoLiderId: input.novoLiderId ?? null,
      descendencia: input.descendencia ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível agendar a multiplicação.");
  }
  return (await res.json()) as Multiplicacao;
}

/**
 * Aprova uma multiplicação. Bloqueada (409) enquanto supervisao_ok=false
 * (delta-027); o motivo é propagado para a UI exibir.
 */
export async function approveMultiplicacao(
  token: string,
  multiplicacaoId: string,
): Promise<ApproveResult> {
  const res = await authedFetch(
    token,
    `/multiplicacoes/${multiplicacaoId}/aprovar`,
    { method: "POST", body: JSON.stringify({}) },
  );
  if (res.status === 409) {
    let message = "Aprovação bloqueada: supervisão pendente.";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (isRecord(body.detail) && typeof body.detail.message === "string") {
        message = body.detail.message;
      }
    } catch {
      /* mantém default */
    }
    throw new ApiError(409, message);
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível aprovar a multiplicação.");
  }
  return (await res.json()) as ApproveResult;
}

// ---------------------------------------------------------------------------
// Derivações de UI
// ---------------------------------------------------------------------------
/** delta-027: aprovação só é liberada quando a supervisão assinou. */
export function canApprove(m: Multiplicacao): boolean {
  return m.supervisaoOk && m.status !== "aprovada" && m.status !== "concluida";
}

export type MultTab = "agendadas" | "sem-agendamento" | "aptos" | "historico";

/** Classifica uma multiplicação na aba correspondente do #enviar. */
export function classifyMult(m: Multiplicacao): Exclude<MultTab, "aptos"> {
  if (m.status === "sem_agendamento" || (!m.dataPrevista && m.status !== "aprovada")) {
    return "sem-agendamento";
  }
  if (m.status === "aprovada" || m.status === "concluida") return "historico";
  return "agendadas";
}
