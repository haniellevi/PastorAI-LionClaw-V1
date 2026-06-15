/**
 * Cliente da API de contatos/pipeline (telas #ganhar e #contatos).
 * Consome os endpoints do backend (sprint-004/005):
 *
 *   GET  /contacts                 -> Page<Contact>   (api-contacts)
 *   POST /contacts                 -> { contact, deduped }  (api-create-contact)
 *   POST /contacts/{id}/cell       -> Contact         (api-link-cell)
 *   GET  /pipeline?etapa=ganhar    -> Page<Contact>   (api-pipeline)
 *   PUT  /pipeline                 -> PipelineResult  (api-pipeline / promover)
 *
 * Reaproveita o transporte autenticado e o tratamento de 401 (sessão expirada)
 * do dashboard-api. 409 em /contacts/{id}/cell carrega o motivo (célula inativa
 * ou sem líder); 409 em PUT /pipeline carrega o critério de promoção não atendido.
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
  presencasCelula: number;
  aceitouJesus: boolean;
  celulaId: string | null;
  liderId: string | null;
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

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchContacts(
  token: string,
  pageSize = 200,
): Promise<Page<Contact>> {
  const res = await authedFetch(token, `/contacts?page=1&pageSize=${pageSize}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar os contatos.");
  }
  return (await res.json()) as Page<Contact>;
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
  visitante: "accent",
  discipulo: "accent",
  membro: "muted",
  lider: "muted",
  pastor: "muted",
};

const TIPO_LABEL: Record<string, string> = {
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
  if (c.tipo === "lider" || c.tipo === "pastor") {
    return { tone: "muted", label: "—" };
  }
  return { tone: "warn", label: "Sem acompanhamento" };
}
