/**
 * Cliente da API do agente de IA (tela #agente).
 * Consome o backend (sprints 007/009):
 *
 *   POST /agent/credential  {provedor, apiKey} -> {status, provedor, validado}  (US-27 / RNF-03)
 *   PUT  /agent/config      -> {nome, tom, comportamento, publicoAlvo, acessos, ativo}  (US-28)
 *   POST /agent/crons       -> {id, nome, frequencia, gatilhoEstado, acao, ativo}
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - a chave nunca é exibida após salvar (RNF-03); chave inválida NÃO ativa a
 *    credencial (status=invalid);
 *  - ativar o agente (ativo=true) exige credencial validada+ativa (409);
 *  - o gatilho de estado do cron é validado antes de salvar (422 quando inválido).
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Provedores BYO. O backend valida e cifra a chave (apenas `openai` ativo hoje). */
export type LlmProvider = "openai" | "anthropic" | "google";

export interface LlmProviderOption {
  code: LlmProvider;
  label: string;
  /** Provedor habilitado no backend (validação real da chave). */
  enabled: boolean;
}

export const LLM_PROVIDERS: LlmProviderOption[] = [
  { code: "openai", label: "OpenAI", enabled: true },
  { code: "anthropic", label: "Anthropic", enabled: false },
  { code: "google", label: "Google (Gemini)", enabled: false },
];

export interface SaveCredentialResult {
  status: "active" | "invalid";
  provedor: string;
  validado: boolean;
}

export interface AgentConfig {
  nome: string | null;
  tom: string | null;
  comportamento: string;
  publicoAlvo: string[] | null;
  acessos: string[] | null;
  ativo: boolean;
}

export interface CronResult {
  id: string;
  nome: string;
  frequencia: string;
  gatilhoEstado: string | null;
  acao: string | null;
  ativo: boolean;
}

/** Gatilhos de estado válidos (espelha VALID_CRON_GATILHOS no backend). */
export const CRON_TRIGGERS = [
  { code: "relatorio_pendente", label: "Relatório pendente" },
  { code: "conexao_pendente", label: "Conexão de célula pendente" },
  { code: "fonovisita_pendente", label: "Fonovisita pendente" },
  { code: "visitante_novo", label: "Novo visitante" },
  { code: "decisao_registrada", label: "Decisão registrada" },
  { code: "consolidacao_aberta", label: "Consolidação aberta" },
  { code: "multiplicacao_agendada", label: "Multiplicação agendada" },
] as const;

/** Ativação bloqueada por falta de credencial validada (409). */
export class AgentCredentialRequiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentCredentialRequiredError";
  }
}

/** Status atual da credencial (sem a chave — RNF-03). */
export interface CredentialStatus {
  status: "active" | "invalid" | "none";
  provedor: string | null;
}

/** Config salva do agente; `configured=false` quando ainda não há. */
export interface AgentConfigStatus {
  configured: boolean;
  nome: string | null;
  tom: string | null;
  comportamento: string | null;
  publicoAlvo: string[] | null;
  acessos: string[] | null;
  ativo: boolean;
}

/** Lê o status da credencial (pra tela indicar "chave configurada" ao abrir). */
export async function fetchCredentialStatus(token: string): Promise<CredentialStatus> {
  const res = await authedFetch(token, "/agent/credential");
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar a credencial.");
  }
  return (await res.json()) as CredentialStatus;
}

/** Lê a configuração de comportamento salva. */
export async function fetchAgentConfig(token: string): Promise<AgentConfigStatus> {
  const res = await authedFetch(token, "/agent/config");
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar a configuração do agente.");
  }
  return (await res.json()) as AgentConfigStatus;
}

/** Lista os agendamentos salvos. */
export async function fetchCrons(token: string): Promise<CronResult[]> {
  const res = await authedFetch(token, "/agent/crons");
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os agendamentos.");
  }
  return (await res.json()) as CronResult[];
}

export async function saveCredential(
  token: string,
  payload: { provedor: LlmProvider; apiKey: string },
): Promise<SaveCredentialResult> {
  const res = await authedFetch(token, "/agent/credential", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.status === 422) {
    const detail = await readDetail(res);
    throw new ApiError(422, detail ?? "Provedor não suportado.");
  }
  if (res.status === 502) {
    throw new ApiError(502, "Não foi possível validar a credencial com o provedor.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar a credencial.");
  }
  return (await res.json()) as SaveCredentialResult;
}

export async function saveAgentConfig(
  token: string,
  payload: {
    comportamento: string;
    nome?: string | null;
    tom?: string | null;
    publicoAlvo?: string[] | null;
    acessos?: string[] | null;
    ativo: boolean;
  },
): Promise<AgentConfig> {
  const res = await authedFetch(token, "/agent/config", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new AgentCredentialRequiredError(
      detail ?? "Ative uma credencial de IA validada antes de ligar o agente.",
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar o comportamento.");
  }
  return (await res.json()) as AgentConfig;
}

export async function createCron(
  token: string,
  payload: {
    nome: string;
    frequencia: string;
    gatilhoEstado?: string | null;
    acao?: string | null;
    ativo: boolean;
  },
): Promise<CronResult> {
  const res = await authedFetch(token, "/agent/crons", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.status === 422) {
    const detail = await readDetail(res);
    throw new ApiError(422, detail ?? "Gatilho de estado inválido.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar o agendamento.");
  }
  return (await res.json()) as CronResult;
}
