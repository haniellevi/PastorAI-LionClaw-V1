/**
 * Cliente da API de multiplicações — Central de Célula (PR3–PR9).
 *
 * A multiplicação transacional/idempotente é criada como solicitação
 * (`POST /cell-requests` tipo `multiplicacao`, em cell-requests-api.ts) e
 * decidida na aprovação da Central. Este módulo expõe apenas a LEITURA
 * consolidada:
 *
 *   GET /multiplicacoes -> { pendentes, registradas }   (superfície da Central)
 *
 * O fluxo direto legado (`POST /multiplicacoes` / `/aprovar`) foi removido do
 * backend; não há mais cliente para ele aqui.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

// ===========================================================================
// Contrato snake_case, espelhando app/routers/multiplicacoes.py::MultiplicacoesListOut
// ===========================================================================

/** Multiplicação pendente = solicitação tipo `multiplicacao` `aguardando`. */
export interface MultiplicacaoPendente {
  id: string;
  celula_id: string;
  solicitante_id: string | null;
  tipo: string;
  status: string;
  payload_proposto: Record<string, unknown>;
  /** ISO-8601 ou null. */
  created_at: string | null;
}

/** Multiplicação registrada (aplicada em transação após a aprovação). */
export interface MultiplicacaoRegistrada {
  id: string;
  celula_id: string;
  celula_nova_id: string | null;
  solicitacao_id: string | null;
  novo_lider_id: string | null;
  status: string | null;
  /** ISO date (YYYY-MM-DD) ou null. */
  data_prevista: string | null;
  descendencia: string | null;
  idempotency_key: string | null;
  /** ISO-8601 ou null. */
  created_at: string | null;
}

/** Saída de GET /multiplicacoes (MultiplicacoesListOut). */
export interface MultiplicacoesListOut {
  pendentes: MultiplicacaoPendente[];
  registradas: MultiplicacaoRegistrada[];
}

/**
 * Lista as multiplicações da igreja: pendentes (solicitações tipo `multiplicacao`
 * aguardando) e registradas (já aplicadas). Endpoint da Central (pastor/admin):
 * responde 403 para os demais papéis.
 */
export async function getMultiplicacoesList(
  token: string,
): Promise<MultiplicacoesListOut> {
  const res = await authedFetch(token, `/multiplicacoes`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar as multiplicações.");
  }
  return (await res.json()) as MultiplicacoesListOut;
}
