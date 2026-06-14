/**
 * Cliente da API de consolidação (#consolidar · #consol-individual).
 * Consome os endpoints do backend (sprint-005):
 *
 *   POST /consolidacao/decisao            -> LaunchDecisionResult  (api-launch-decision)
 *   POST /pipeline/assign-consolidador    -> AssignResult          (api-pipeline)
 *   POST /pipeline/advance-stage          -> AdvanceStageResult     (api-pipeline)
 *
 * Regras de domínio espelhadas do backend (app/domain/consolidation.py):
 *  - fluxo visitante abre prazo de conexão de 24h (deadline-badge);
 *  - a confirmação de etapa é restrita ao consolidador responsável (gate de
 *    identidade — 403); concluir é bloqueado enquanto houver etapa obrigatória
 *    pendente (409 com etapasPendentes).
 *
 * Reaproveita o transporte autenticado e o tratamento de 401 do dashboard-api.
 */

import {
  ApiError,
  authedFetch,
  isRecord,
  readDetail,
} from "./dashboard-api";
import type { Contact } from "./contacts-api";
import type { Role } from "./roles";

// ---------------------------------------------------------------------------
// Papéis com acesso à consolidação (CONSOLIDATION_ROLES + admin implícito)
// ---------------------------------------------------------------------------
export const CONSOLIDATION_ROLES: readonly Role[] = ["admin", "pastor", "lider_consol"];

/** #consolidar / #consol-individual só abrem para esses papéis. */
export function canConsolidate(roles: readonly Role[]): boolean {
  return roles.some((r) => CONSOLIDATION_ROLES.includes(r));
}

// ---------------------------------------------------------------------------
// Vínculo da decisão (decision_vinculo)
// ---------------------------------------------------------------------------
export type DecisionVinculo = "celula" | "visitante";

export interface LaunchDecisionInput {
  pessoa: string;
  origem?: string | null;
  vinculo: DecisionVinculo;
  celulaId?: string | null;
}

export interface LaunchDecisionResult {
  status: string;
  consolidacaoId: string;
  etapa: string;
  /** ISO-8601 do prazo de conexão (apenas fluxo visitante) ou null. */
  prazoConexao: string | null;
  responsavel: string | null;
}

export interface AssignResult {
  status: string;
  consolidacaoId: string;
  responsavelId: string;
}

export interface AdvanceStageResult {
  status: string;
  consolidacaoId: string;
  progresso: number;
  concluida: boolean;
  etapasPendentes: string[];
}

/** 409 ao concluir com etapas obrigatórias pendentes (carrega os nomes). */
export class StageGateError extends ApiError {
  readonly etapasPendentes: string[];
  constructor(message: string, etapasPendentes: string[]) {
    super(409, message);
    this.name = "StageGateError";
    this.etapasPendentes = etapasPendentes;
  }
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
/**
 * Lança uma decisão por Jesus e abre a consolidação (US-37/40).
 * Fluxo visitante define prazo de conexão de 24h; fluxo célula assume a
 * consolidação no responsável (sem prazo de 24h).
 */
export async function launchDecision(
  token: string,
  input: LaunchDecisionInput,
): Promise<LaunchDecisionResult> {
  const res = await authedFetch(token, `/consolidacao/decisao`, {
    method: "POST",
    body: JSON.stringify({
      pessoa: input.pessoa,
      origem: input.origem ?? null,
      vinculo: input.vinculo,
      celulaId: input.celulaId ?? null,
    }),
  });
  if (res.status === 403) {
    throw new ApiError(403, "Você não tem permissão para lançar decisões.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível lançar a decisão.");
  }
  return (await res.json()) as LaunchDecisionResult;
}

/** Atribui o consolidador responsável (habilita a confirmação de etapas). */
export async function assignConsolidador(
  token: string,
  consolidacaoId: string,
  responsavelId: string,
): Promise<AssignResult> {
  const res = await authedFetch(token, `/pipeline/assign-consolidador`, {
    method: "POST",
    body: JSON.stringify({ consolidacaoId, responsavelId }),
  });
  if (res.status === 403) {
    throw new ApiError(403, "Você não tem permissão para atribuir consolidador.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível atribuir o consolidador.");
  }
  return (await res.json()) as AssignResult;
}

/**
 * Confirma uma etapa da trilha individual ou conclui a consolidação.
 * Gate de identidade (403): apenas o consolidador responsável pode confirmar.
 * Concluir é bloqueado (409 StageGateError) enquanto houver etapa obrigatória
 * pendente.
 */
export async function advanceStage(
  token: string,
  input: { consolidacaoId: string; etapa?: string | null; concluir?: boolean },
): Promise<AdvanceStageResult> {
  const res = await authedFetch(token, `/pipeline/advance-stage`, {
    method: "POST",
    body: JSON.stringify({
      consolidacaoId: input.consolidacaoId,
      etapa: input.etapa ?? null,
      concluir: input.concluir ?? false,
    }),
  });
  if (res.status === 403) {
    let message = "Apenas o consolidador responsável pode confirmar etapas.";
    const detail = await readDetail(res);
    if (detail) message = detail;
    throw new ApiError(403, message);
  }
  if (res.status === 409) {
    let message = "Há etapas obrigatórias pendentes.";
    let pendentes: string[] = [];
    try {
      const body = (await res.json()) as { detail?: unknown };
      const d = body.detail;
      if (typeof d === "string") {
        message = d;
      } else if (isRecord(d)) {
        if (typeof d.message === "string") message = d.message;
        if (Array.isArray(d.etapasPendentes)) {
          pendentes = d.etapasPendentes.filter((x): x is string => typeof x === "string");
        }
      }
    } catch {
      /* mantém defaults */
    }
    throw new StageGateError(message, pendentes);
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível avançar a etapa.");
  }
  return (await res.json()) as AdvanceStageResult;
}

// ---------------------------------------------------------------------------
// Derivações de UI (trilha individual)
// ---------------------------------------------------------------------------
/** Etapas obrigatórias da trilha individual (gate de conclusão). */
export const MANDATORY_ETAPAS = [
  "aceitou_jesus",
  "conectou_celula",
  "fonovisita",
] as const;

export type MandatoryEtapa = (typeof MANDATORY_ETAPAS)[number];

export interface EtapaMeta {
  label: string;
  desc: string;
  /** Etapa opcional, fora do gate de conclusão (apenas exibição). */
  optional?: boolean;
}

/** Passos da trilha exibidos no track (inclui o passo opcional de visitas). */
export const TRACK_STEPS: ReadonlyArray<{ etapa: string } & EtapaMeta> = [
  {
    etapa: "aceitou_jesus",
    label: "Aceitou Jesus",
    desc: "Registrado pela consolidação ou pelo líder de célula",
  },
  {
    etapa: "conectou_celula",
    label: "Conectou numa célula",
    desc: "Vínculo com a célula mais indicada",
  },
  {
    etapa: "fonovisita",
    label: "Fonovisita",
    desc: "Primeiro contato do consolidador",
  },
  {
    etapa: "visitas",
    label: "Visitas de consolidação",
    desc: "Quantidade definida pelas regras da igreja",
    optional: true,
  },
];

/**
 * Etapas implicitamente concluídas a partir do registro da pessoa (estado
 * derivado, sem endpoint de leitura de consolidação): aceitou Jesus, vínculo de
 * célula e acompanhamento consolidado cobrem a fonovisita.
 */
export function derivedStages(c: Contact): Set<string> {
  const set = new Set<string>();
  if (c.aceitouJesus) set.add("aceitou_jesus");
  if (c.celulaId) set.add("conectou_celula");
  const acomp = (c.acompanhamento ?? "").toLowerCase();
  if (acomp === "consolidado" || c.subetapa === "consolidado") {
    set.add("aceitou_jesus");
    set.add("conectou_celula");
    set.add("fonovisita");
  }
  return set;
}

/** Une o estado derivado com as etapas confirmadas na sessão. */
export function mergeStages(
  derived: Set<string>,
  confirmed: readonly string[] | undefined,
): Set<string> {
  const set = new Set(derived);
  for (const e of confirmed ?? []) set.add(e);
  return set;
}

/** Progresso (0-100) a partir das etapas obrigatórias concluídas. */
export function computeProgresso(stages: Set<string>): number {
  const done = MANDATORY_ETAPAS.filter((e) => stages.has(e)).length;
  return Math.round((done * 100) / MANDATORY_ETAPAS.length);
}

/** Quantas etapas obrigatórias foram concluídas (para o rótulo "n / N"). */
export function countMandatory(stages: Set<string>): number {
  return MANDATORY_ETAPAS.filter((e) => stages.has(e)).length;
}

/** Etapas obrigatórias ainda pendentes. */
export function pendingMandatory(stages: Set<string>): MandatoryEtapa[] {
  return MANDATORY_ETAPAS.filter((e) => !stages.has(e));
}

/** Próxima etapa obrigatória a confirmar (ou null se tudo concluído). */
export function nextMandatory(stages: Set<string>): MandatoryEtapa | null {
  return pendingMandatory(stages)[0] ?? null;
}

/** Conclusão liberada apenas com todas as etapas obrigatórias concluídas. */
export function canConclude(stages: Set<string>): boolean {
  return pendingMandatory(stages).length === 0;
}

/** Rótulo curto de uma etapa (para mensagens de pendência). */
export function etapaLabel(etapa: string): string {
  return TRACK_STEPS.find((s) => s.etapa === etapa)?.label ?? etapa;
}
