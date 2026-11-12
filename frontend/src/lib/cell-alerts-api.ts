/**
 * RF-26: alertas ao líder de célula.
 *
 *   GET /cell-alert-rules          -> regras da igreja (somente admin)
 *   PUT /cell-alert-rules/{tipo}   -> liga/desliga e ajusta parâmetros
 *   GET /cells/me/alerts           -> alertas abertos das células que lidero
 *
 * A baixa reusa POST /cells/{id}/alerts/{aid}/baixar (cells-api.baixarAlert).
 */
import { ApiError, authedFetch, readDetail } from "./dashboard-api";

export interface AlertRuleParam {
  nome: string;
  rotulo: string;
  unidade: string;
  minimo: number;
  maximo: number;
  padrao: number;
  valor: number;
}

export interface AlertRule {
  tipo: string;
  titulo: string;
  descricao: string;
  ativo: boolean;
  parametros: AlertRuleParam[];
  atualizadoEm: string | null;
}

export interface AlertRules {
  processamentoLiberado: boolean;
  regras: AlertRule[];
}

export interface MyCellAlert {
  id: string;
  celulaId: string;
  celulaNome: string;
  pessoaId: string | null;
  /** Nome só quando o servidor confirma que você já vê essa pessoa em Pessoas. */
  pessoaNome?: string | null;
  gatilho: string | null;
  acaoEsperada: string | null;
}

export async function getAlertRules(token: string, signal?: AbortSignal): Promise<AlertRules> {
  const res = await authedFetch(token, "/cell-alert-rules", { cache: "no-store", signal });
  if (!res.ok) throw new ApiError(res.status, "Não foi possível carregar as regras de alerta.");
  return (await res.json()) as AlertRules;
}

export async function saveAlertRule(
  token: string,
  tipo: string,
  ativo: boolean,
  parametros: Record<string, number>,
  signal?: AbortSignal,
): Promise<AlertRule> {
  const res = await authedFetch(token, `/cell-alert-rules/${encodeURIComponent(tipo)}`, {
    method: "PUT",
    cache: "no-store",
    signal,
    body: JSON.stringify({ ativo, parametros }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar a regra.");
  }
  return (await res.json()) as AlertRule;
}

export async function getMyCellAlerts(token: string): Promise<MyCellAlert[]> {
  const res = await authedFetch(token, "/cells/me/alerts", { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, "Não foi possível carregar os alertas.");
  return (await res.json()) as MyCellAlert[];
}
