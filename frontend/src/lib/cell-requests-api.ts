/**
 * Cliente da API de solicitações de campo sensível / multiplicação (célula).
 * Consome os endpoints do backend (cell_requests.py):
 *
 *   POST /cell-requests                        -> CellRequest        (201; nasce 'aguardando')
 *   GET  /cell-requests[?status=]              -> Page<CellRequest>  (líder: as suas; Central: da igreja)
 *   GET  /cell-requests/{id}                   -> CellRequestDetail  (+ trilha de eventos)
 *   PUT  /cell-requests/{id}/resubmit          -> CellRequest        (autor, só em ajuste_solicitado)
 *   POST /cell-requests/{id}/cancel            -> CellRequest        (autor)
 *   POST /cell-requests/{id}/approve           -> CellRequest        (Central; exige idempotency_key p/ multiplicação)
 *   POST /cell-requests/{id}/reject            -> CellRequest        (Central; observacao_central obrigatória)
 *   POST /cell-requests/{id}/request-adjustment -> CellRequest       (Central; observacao_central obrigatória)
 *
 * Contrato snake_case (`payload_proposto`, `observacao_central`, `decidido_em`).
 * 409 na criação = já existe solicitação aberta conflitante (matriz E13/6.8).
 * Reaproveita o transporte autenticado (authedFetch) e o envelope Page.
 */

import {
  ApiError,
  authedFetch,
  isRecord,
  readDetail,
  type Page,
} from "./dashboard-api";

export type { Page } from "./dashboard-api";

/**
 * Tipo da solicitação (discriminador de `payload_proposto`, 6.3):
 * alteração de dia/horário/endereço/anfitrião/auxiliar, transferência/remoção
 * de membro e multiplicação.
 */
export type CellRequestType =
  | "alterar_dia"
  | "alterar_horario"
  | "alterar_endereco"
  | "alterar_anfitriao"
  | "alterar_auxiliar"
  | "transferir_membro"
  | "remover_membro"
  | "multiplicacao";

/** Status do ciclo da solicitação. */
export type CellRequestStatus =
  | "aguardando"
  | "ajuste_solicitado"
  | "aprovada"
  | "rejeitada"
  | "cancelada";

/** Solicitação (CellRequestOut). `payload_proposto` mantém o snake_case do backend. */
export interface CellRequest {
  id: string;
  celula_id: string;
  solicitante_id: string | null;
  pessoa_id: string | null;
  tipo: string;
  status: string;
  payload_proposto: Record<string, unknown>;
  payload_atual: Record<string, unknown> | null;
  motivo: string | null;
  observacao_central: string | null;
  decidido_por: string | null;
  /** ISO-8601 ou null. */
  decidido_em: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Evento append-only da trilha de auditoria (CellRequestEventOut). */
export interface CellRequestEvent {
  id: string;
  acao: string;
  autor_id: string | null;
  de_status: string | null;
  para_status: string | null;
  observacao: string | null;
  payload_snapshot: Record<string, unknown>;
  created_at: string | null;
}

/** Detalhe da solicitação com a trilha de eventos (CellRequestDetailOut). */
export interface CellRequestDetail extends CellRequest {
  eventos: CellRequestEvent[];
}

/** Payload de criação (CreateCellRequest). */
export interface CreateCellRequestInput {
  celula_id: string;
  tipo: CellRequestType | string;
  payload_proposto?: Record<string, unknown> | null;
  motivo?: string | null;
}

/** Conflito (409) — já existe solicitação aberta conflitante (E13/6.8). */
export class CellRequestConflictError extends ApiError {
  constructor(message: string) {
    super(409, message);
    this.name = "CellRequestConflictError";
  }
}

async function detailOrFallback(res: Response, fallback: string): Promise<string> {
  const detail = await readDetail(res);
  return detail ?? fallback;
}

/**
 * Cria uma solicitação. Nasce `aguardando` e NÃO altera o dado real. 409 se já
 * existir solicitação aberta conflitante do mesmo tipo/alvo (matriz E13/6.8).
 */
export async function createRequest(
  token: string,
  input: CreateCellRequestInput,
): Promise<CellRequest> {
  const res = await authedFetch(token, `/cell-requests`, {
    method: "POST",
    body: JSON.stringify({
      celula_id: input.celula_id,
      tipo: input.tipo,
      payload_proposto: input.payload_proposto ?? null,
      motivo: input.motivo ?? null,
    }),
  });
  if (res.status === 409) {
    let message = "Já existe uma solicitação aberta conflitante.";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (isRecord(body.detail) && typeof body.detail.message === "string") {
        message = body.detail.message;
      }
    } catch {
      /* mantém default */
    }
    throw new CellRequestConflictError(message);
  }
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível criar a solicitação."));
  }
  return (await res.json()) as CellRequest;
}

/** Lista solicitações (líder: as suas; Central: da igreja), com filtro por status. */
export async function listRequests(
  token: string,
  statusFilter?: CellRequestStatus | string,
  page = 1,
  pageSize = 50,
): Promise<Page<CellRequest>> {
  const query = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  });
  if (statusFilter) query.set("status", statusFilter);
  const res = await authedFetch(token, `/cell-requests?${query.toString()}`);
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível carregar as solicitações."));
  }
  return (await res.json()) as Page<CellRequest>;
}

/** Detalhe de uma solicitação + trilha de eventos. */
export async function getRequest(
  token: string,
  requestId: string,
): Promise<CellRequestDetail> {
  const res = await authedFetch(token, `/cell-requests/${requestId}`);
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível abrir a solicitação."));
  }
  return (await res.json()) as CellRequestDetail;
}

/** Reenvia (autor) uma solicitação em `ajuste_solicitado`, opcionalmente com novo payload. */
export async function resubmitRequest(
  token: string,
  requestId: string,
  payloadProposto?: Record<string, unknown> | null,
): Promise<CellRequest> {
  const res = await authedFetch(token, `/cell-requests/${requestId}/resubmit`, {
    method: "PUT",
    body: JSON.stringify({ payload_proposto: payloadProposto ?? null }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível reenviar a solicitação."));
  }
  return (await res.json()) as CellRequest;
}

/** Cancela (autor) uma solicitação em `aguardando`/`ajuste_solicitado` (E12). */
export async function cancelRequest(
  token: string,
  requestId: string,
): Promise<CellRequest> {
  const res = await authedFetch(token, `/cell-requests/${requestId}/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível cancelar a solicitação."));
  }
  return (await res.json()) as CellRequest;
}

/**
 * Aprova (Central) a solicitação sem editar o payload. Multiplicação exige
 * `idempotencyKey` (reprocessar a mesma chave não duplica).
 */
export async function approveRequest(
  token: string,
  requestId: string,
  idempotencyKey?: string,
): Promise<CellRequest> {
  const res = await authedFetch(token, `/cell-requests/${requestId}/approve`, {
    method: "POST",
    body: JSON.stringify({ idempotency_key: idempotencyKey ?? null }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível aprovar a solicitação."));
  }
  return (await res.json()) as CellRequest;
}

/** Rejeita (Central) a solicitação; `observacaoCentral` é obrigatória (422 se ausente). */
export async function rejectRequest(
  token: string,
  requestId: string,
  observacaoCentral: string,
): Promise<CellRequest> {
  const res = await authedFetch(token, `/cell-requests/${requestId}/reject`, {
    method: "POST",
    body: JSON.stringify({ observacao_central: observacaoCentral }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível rejeitar a solicitação."));
  }
  return (await res.json()) as CellRequest;
}

/** Pede ajuste (Central); `observacaoCentral` é obrigatória (422 se ausente). */
export async function requestAdjustment(
  token: string,
  requestId: string,
  observacaoCentral: string,
): Promise<CellRequest> {
  const res = await authedFetch(
    token,
    `/cell-requests/${requestId}/request-adjustment`,
    {
      method: "POST",
      body: JSON.stringify({ observacao_central: observacaoCentral }),
    },
  );
  if (!res.ok) {
    throw new ApiError(res.status, await detailOrFallback(res, "Não foi possível solicitar ajuste."));
  }
  return (await res.json()) as CellRequest;
}
