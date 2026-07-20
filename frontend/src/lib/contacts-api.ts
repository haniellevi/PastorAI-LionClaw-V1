/**
 * Cliente da API de contatos/pipeline (telas #ganhar e #contatos).
 * Consome os endpoints do backend (sprint-004/005):
 *
 *   GET  /contacts                 -> Page<Contact>   (api-contacts)
 *   POST /contacts                 -> { contact, deduped }  (api-create-contact)
 *   POST /contacts/{id}/cell       -> Contact         (api-link-cell)
 *   GET  /pipeline?etapa=ganhar    -> Page<Contact>   (api-pipeline)
 *   PUT  /pipeline                 -> PipelineResult  (api-pipeline / promover)
 *   GET  /contacts/{id}/offboarding-preflight -> OffboardingPreflight (M7B-W3.2B)
 *   POST /contacts/{id}/archive    -> ArchiveContactResult (M7B-W3.2B)
 *
 * Reaproveita o transporte autenticado e o tratamento de 401 (sessão expirada)
 * do dashboard-api. 409 em /contacts/{id}/cell carrega o motivo (célula inativa
 * ou sem líder); 409 em PUT /pipeline carrega o critério de promoção não atendido.
 * 409 em /contacts/{id}/archive carrega o MESMO formato do preflight (bloqueadores
 * revalidados dentro da transação travada do backend — ver ArchiveBlockedError).
 */

import {
  ApiError,
  authedFetch,
  isRecord,
  readDetail,
  type Page,
} from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Projeção de pessoa retornada por /contacts e /pipeline (ContactOut). */
export interface Contact {
  id: string;
  nome: string;
  telefone: string;
  email: string | null;
  genero: string | null;
  tipo: string | null;
  etapa: string | null;
  subetapa: string | null;
  acompanhamento: string | null;
  semInteresse: boolean;
  semInteresseMotivo: string | null;
  presencasCelula: number;
  aceitouJesus: boolean;
  celulaId: string | null;
  liderId: string | null;
  /** Realizou o Reencontro — apto a liderar célula (regra 2026-07-06). */
  aptoLider: boolean;
  /** Derivado no backend: lidera célula ATIVA (celulas.lider_id). */
  liderDeCelula: boolean;
  /**
   * FECH-06/REATIVAR-1: pessoa arquivada (pessoas.arquivada_em preenchido).
   * Opcional porque projeções derivadas do detalhe (toContact) não a trazem —
   * ausente equivale a false.
   */
  arquivada?: boolean;
}

/**
 * Detalhe completo de uma pessoa (GET /contacts/{id}) — alimenta o painel de
 * dados do contato no chat (Parte B). Estende `Contact` com campos cadastrais e
 * de jornada e já traz os nomes resolvidos de célula e líder.
 */
export interface ContactDetail {
  id: string;
  nome: string;
  telefone: string;
  email: string | null;
  genero: string | null;
  faixaEtaria: string | null;
  endereco: string | null;
  tipo: string | null;
  etapa: string | null;
  subetapa: string | null;
  acompanhamento: string | null;
  semInteresse: boolean;
  semInteresseMotivo: string | null;
  presencasCelula: number;
  aceitouJesus: boolean;
  celulaId: string | null;
  celulaNome: string | null;
  liderId: string | null;
  liderNome: string | null;
  aptoLider: boolean;
  liderDeCelula: boolean;
  consentimento: boolean;
  optout: boolean;
  origem: string | null;
  primeiroContato: string | null;
  criadoEm: string | null;
}

export interface CreateContactInput {
  nome: string;
  telefone: string;
  email?: string | null;
  genero?: "m" | "f" | null;
  tipo?: string | null;
  origem?: string | null;
}

export interface CreateContactResult {
  contact: Contact;
  /** true quando bateu num (telefone, igreja) já existente — sem duplicar. */
  deduped: boolean;
}

export interface PromoteResult {
  status: string;
  pessoaId: string;
  etapa: string | null;
  subetapa: string | null;
  tipo: string | null;
}

/**
 * Bloqueador, efeito automático ou item preservado do arquivamento de Pessoa
 * (M7B-W3.2B). Mesmo formato nas 3 listas — espelha PreflightItemOut do
 * backend (chaves em snake_case, sem alias de camelCase neste endpoint).
 */
export interface OffboardingPreflightItem {
  tipo: string;
  rotulo: string;
  recurso_id: string | null;
  recurso_nome: string | null;
  acao_recomendada: string | null;
}

/** Resposta de GET /contacts/{id}/offboarding-preflight (admin-only). */
export interface OffboardingPreflight {
  pessoa_id: string;
  pode_arquivar: boolean;
  bloqueadores: OffboardingPreflightItem[];
  automaticos: OffboardingPreflightItem[];
  preservados: OffboardingPreflightItem[];
}

/**
 * Resposta de POST /contacts/{id}/reactivate-communications (FECH-05/OPTIN-1,
 * admin/pastor). `ja_ativa` = chamada idempotente (a pessoa não estava em
 * opt-out; nada mudou). Chaves em snake_case, espelhando o backend.
 */
export interface ReactivateCommunicationsResult {
  pessoa_id: string;
  optout: boolean;
  termo_versao: string;
  reativada_por: string | null;
  ja_ativa: boolean;
}

/** Resposta de POST /contacts/{id}/archive (admin-only). */
export interface ArchiveContactResult {
  pessoa_id: string;
  arquivada: boolean;
  arquivada_em: string;
  arquivada_por: string | null;
  arquivada_motivo: string;
  /** true quando a pessoa já estava arquivada (chamada idempotente). */
  ja_arquivada: boolean;
}

/**
 * Resposta de POST /contacts/{id}/unarchive (FECH-06/REATIVAR-1, admin/pastor).
 * Chaves em snake_case, espelhando o backend.
 */
export interface UnarchiveContactResult {
  pessoa_id: string;
  arquivada: boolean;
  reativada_por: string | null;
}

/**
 * 409 de /archive: o backend revalida o preflight na mesma transação travada
 * e devolve a lista estruturada de bloqueadores (SEC-4B) — o cliente reexibe
 * exatamente o que mudou desde o GET de preflight, em vez de um texto genérico.
 */
export class ArchiveBlockedError extends Error {
  readonly preflight: OffboardingPreflight;
  constructor(preflight: OffboardingPreflight) {
    super("Novos vínculos impedem o arquivamento agora.");
    this.name = "ArchiveBlockedError";
    this.preflight = preflight;
  }
}

function isOffboardingPreflight(value: unknown): value is OffboardingPreflight {
  return isRecord(value) && Array.isArray(value.bloqueadores);
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchContacts(
  token: string,
  pageSize = 200,
): Promise<Page<Contact>> {
  // Backend limita pageSize a 200 (MAX_PAGE_SIZE); igrejas no plano acima_201
  // passam disso, então busca todas as páginas para não truncar a lista.
  const items: Contact[] = [];
  let page = 1;
  let total = 0;
  for (;;) {
    const res = await authedFetch(token, `/contacts?page=${page}&pageSize=${pageSize}`);
    if (!res.ok) {
      throw new ApiError(res.status, "Não foi possível carregar os contatos.");
    }
    const batch = (await res.json()) as Page<Contact>;
    items.push(...batch.items);
    total = batch.total;
    if (batch.items.length === 0 || items.length >= total) break;
    page += 1;
  }
  return { items, page: 1, pageSize, total };
}

/** Detalhe completo de uma pessoa para o painel do chat (404 → erro). */
export async function fetchContactDetail(
  token: string,
  contactId: string,
): Promise<ContactDetail> {
  const res = await authedFetch(token, `/contacts/${contactId}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar os dados do contato.");
  }
  return (await res.json()) as ContactDetail;
}

export async function fetchPipeline(
  token: string,
  etapa?: string,
  pageSize = 200,
): Promise<Page<Contact>> {
  const query = new URLSearchParams({ page: "1", pageSize: String(pageSize) });
  if (etapa) query.set("etapa", etapa);
  const res = await authedFetch(token, `/pipeline?${query.toString()}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a base de entrada.");
  }
  return (await res.json()) as Page<Contact>;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
export async function createContact(
  token: string,
  input: CreateContactInput,
): Promise<CreateContactResult> {
  const res = await authedFetch(token, `/contacts`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar o contato.");
  }
  return (await res.json()) as CreateContactResult;
}

export interface UpdateContactInput {
  nome?: string;
  telefone?: string;
  email?: string | null;
  genero?: "m" | "f" | null;
  tipo?: string | null;
  semInteresse?: boolean;
  semInteresseMotivo?: string | null;
  /** Apto a liderar (Reencontro) — só admin; CSIM não pode ser apto (422). */
  aptoLider?: boolean;
}

/**
 * Edita os dados cadastrais de uma pessoa (somente admin no backend — 403 caso
 * contrário). 409 quando o novo telefone colide com outra pessoa da igreja.
 */
export async function updateContact(
  token: string,
  contactId: string,
  input: UpdateContactInput,
): Promise<Contact> {
  const res = await authedFetch(token, `/contacts/${contactId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar as alterações.");
  }
  return (await res.json()) as Contact;
}

/**
 * Vincula um contato a uma célula ativa com líder. Bloqueia (409) célula inativa
 * ou sem líder, propagando a mensagem do backend.
 */
export async function linkContactCell(
  token: string,
  contactId: string,
  celulaId: string,
): Promise<Contact> {
  const res = await authedFetch(token, `/contacts/${contactId}/cell`, {
    method: "POST",
    body: JSON.stringify({ celulaId }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível conectar à célula.");
  }
  return (await res.json()) as Contact;
}

/**
 * Promove uma pessoa na trilha (PUT /pipeline). Para visitante, o backend exige
 * 3+ presenças OU decisão por Jesus; quando não atendido retorna 409 com o motivo.
 */
export async function promoteContact(
  token: string,
  pessoaId: string,
  etapa = "consolidar",
  subetapa?: string,
): Promise<PromoteResult> {
  const res = await authedFetch(token, `/pipeline`, {
    method: "PUT",
    body: JSON.stringify({ pessoaId, etapa, subetapa: subetapa ?? null }),
  });
  if (res.status === 409) {
    let message = "Visitante ainda não atende ao critério de promoção.";
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
    throw new ApiError(res.status, detail ?? "Não foi possível promover.");
  }
  return (await res.json()) as PromoteResult;
}

/**
 * Reativa as comunicações de uma pessoa em opt-out (FECH-05/OPTIN-1).
 * Backend restringe a admin/pastor (403 caso contrário); 404 quando a pessoa
 * não existe ou é de outra igreja (tenant nunca revela existência).
 */
export async function reactivateCommunications(
  token: string,
  contactId: string,
): Promise<ReactivateCommunicationsResult> {
  const res = await authedFetch(
    token,
    `/contacts/${contactId}/reactivate-communications`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(
      res.status,
      detail ?? "Não foi possível reativar as comunicações.",
    );
  }
  return (await res.json()) as ReactivateCommunicationsResult;
}

/**
 * Calcula se `contactId` pode ser arquivada agora (M7B-W3.2B, admin-only).
 * Somente leitura — nenhuma mutação. 403 quando o usuário não é admin; 404
 * quando a pessoa não existe (ou é de outro tenant — RLS nunca revela).
 */
export async function fetchOffboardingPreflight(
  token: string,
  contactId: string,
): Promise<OffboardingPreflight> {
  const res = await authedFetch(token, `/contacts/${contactId}/offboarding-preflight`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(
      res.status,
      detail ?? "Não foi possível verificar se esta pessoa pode ser arquivada.",
    );
  }
  return (await res.json()) as OffboardingPreflight;
}

/**
 * Arquiva `contactId` (M7B-W3.2B, admin-only) — nunca hard delete; motivo
 * obrigatório. 409 revalida o preflight na transação travada e lança
 * `ArchiveBlockedError` com a lista atual de bloqueadores.
 */
export async function archiveContact(
  token: string,
  contactId: string,
  motivo: string,
): Promise<ArchiveContactResult> {
  const res = await authedFetch(token, `/contacts/${contactId}/archive`, {
    method: "POST",
    body: JSON.stringify({ motivo }),
  });
  if (res.status === 409) {
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (isOffboardingPreflight(body.detail)) {
        throw new ArchiveBlockedError(body.detail);
      }
    } catch (err) {
      if (err instanceof ArchiveBlockedError) throw err;
      /* corpo não-JSON: cai no ApiError genérico abaixo */
    }
    throw new ApiError(409, "Não é possível arquivar: há vínculos ativos pendentes.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível arquivar esta pessoa.");
  }
  return (await res.json()) as ArchiveContactResult;
}

/**
 * Desarquiva `contactId` (FECH-06/REATIVAR-1) — a pessoa volta às listas
 * normais. Backend restringe a admin/pastor (403 caso contrário); 404 quando a
 * pessoa não existe ou é de outra igreja (tenant nunca revela existência);
 * 409 quando a pessoa não está arquivada.
 */
export async function unarchiveContact(
  token: string,
  contactId: string,
): Promise<UnarchiveContactResult> {
  const res = await authedFetch(token, `/contacts/${contactId}/unarchive`, {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível reativar esta pessoa.");
  }
  return (await res.json()) as UnarchiveContactResult;
}

// ---------------------------------------------------------------------------
// Derivações de UI (classificação e status)
// ---------------------------------------------------------------------------
export type ContactGroup = "novos-contatos" | "visitantes";

/**
 * Classifica uma pessoa do estágio "ganhar" entre as abas do #ganhar.
 * Novos contatos nunca visitaram (subetapa novo_contato, sem presenças);
 * visitantes já foram à célula/evento e seguem assim até aceitar Jesus ou
 * completar 3 presenças.
 */
export function classifyGanhar(c: Contact): ContactGroup {
  if (c.subetapa === "novo_contato") return "novos-contatos";
  if (c.subetapa === "visitante") return "visitantes";
  return c.presencasCelula > 0 ? "visitantes" : "novos-contatos";
}

/** Critério de promoção de visitante (espelha meets_promotion_criteria do backend). */
export function meetsPromotionCriteria(c: Contact): boolean {
  return (c.presencasCelula ?? 0) >= 3 || c.aceitouJesus;
}

export type StatusTone = "ok" | "warn" | "danger" | "accent" | "muted";

export interface StatusInfo {
  tone: StatusTone;
  label: string;
}

const TIPO_TONE: Record<string, StatusTone> = {
  contato: "warn",
  visitante: "accent",
  discipulo: "accent",
  membro: "muted",
  lider: "muted",
  pastor: "muted",
};

const TIPO_LABEL: Record<string, string> = {
  contato: "Contato",
  visitante: "Visitante",
  discipulo: "Discípulo",
  membro: "Membro",
  lider: "Líder",
  pastor: "Pastor",
};

export function tipoLabel(tipo: string | null): string {
  if (!tipo) return "—";
  return TIPO_LABEL[tipo] ?? tipo.charAt(0).toUpperCase() + tipo.slice(1);
}

export function tipoTone(tipo: string | null): StatusTone {
  if (!tipo) return "muted";
  return TIPO_TONE[tipo] ?? "muted";
}

/**
 * Status de acompanhamento exibido na status-pill (etapa/acompanhamento).
 * Reflete consolidado > em andamento > sem acompanhamento.
 */
export function followStatus(c: Contact): StatusInfo {
  const acomp = (c.acompanhamento ?? "").toLowerCase();
  if (acomp === "consolidado" || c.subetapa === "consolidado") {
    return { tone: "ok", label: "Consolidado" };
  }
  if (acomp === "em_consolidacao" || acomp === "em_andamento" || c.celulaId) {
    return { tone: "accent", label: "Em acompanhamento" };
  }
  // Líder de célula é derivado do vínculo real (não do tipo — regra 2026-07-06).
  if (c.liderDeCelula || c.tipo === "pastor") {
    return { tone: "muted", label: "—" };
  }
  return { tone: "warn", label: "Sem acompanhamento" };
}
