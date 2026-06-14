/**
 * Cliente da API de conversas do inbox (sprint Frontend Inbox & Conexão WhatsApp).
 * Consome conversas e handoff IA/humano do backend (sprint-006).
 *
 * Contratos (SPEC 3.2 / app/routers/conversations.py):
 *   GET  /conversations                    -> Page<ConversationOut>
 *   POST /conversations/{id}/handoff {to}  -> { estado, assumidoPor }
 *
 * Acesso (US-11): o inbox é restrito a papéis privilegiados — admin (implícito),
 * pastor e lider_g12. Líderes de célula recebem 403 no backend; no front o gate
 * de papel evita a chamada e exibe o bloqueio de acesso.
 *
 * Concorrência no handoff (US-12): se outro humano já assumiu, a API responde
 * 409 carregando o `assumidoPor` real para a UI refletir quem detém a conversa.
 */

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, isRecord, readDetail, type Page } from "./dashboard-api";
import type { Role } from "./roles";

export type { Page };

/** Estado da máquina de handoff (conversation_estado). */
export type ConversationEstado = "ia" | "humano" | "aguardando";

export interface Conversation {
  id: string;
  telefone: string;
  pessoaId: string | null;
  nome: string | null;
  estado: ConversationEstado | null;
  ultimaMensagem: string | null;
  naoLidas: number;
  assumidoPor: string | null;
  assumidoEm: string | null;
  esperaDesde: string | null;
}

export interface HandoffResult {
  estado: string;
  assumidoPor: string | null;
}

/**
 * Papéis privilegiados do inbox (US-11). Espelha INBOX_ROLES do backend
 * (app/domain/conversations.py): admin passa implicitamente; pastor e lider_g12
 * têm acesso. Líder de célula/membro nunca acessam.
 */
const INBOX_ROLES: ReadonlySet<Role> = new Set<Role>(["pastor", "lider_g12", "operador"]);

/** True se o conjunto de papéis acumulados pode abrir o inbox (US-11). */
export function canAccessInbox(roles: readonly Role[]): boolean {
  if (roles.includes("admin")) return true;
  return roles.some((r) => INBOX_ROLES.has(r));
}

/** Conflito de concorrência: conversa já assumida por outro usuário (US-12). */
export class ConversationConflictError extends Error {
  readonly estado: string | null;
  readonly assumidoPor: string | null;
  constructor(message: string, estado: string | null, assumidoPor: string | null) {
    super(message);
    this.name = "ConversationConflictError";
    this.estado = estado;
    this.assumidoPor = assumidoPor;
  }
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchConversations(
  token: string,
  pageSize = 100,
): Promise<Page<Conversation>> {
  const res = await authedFetch(token, `/conversations?page=1&pageSize=${pageSize}`);
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito ao inbox.");
  }
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as conversas.");
  }
  return (await res.json()) as Page<Conversation>;
}

// ---------------------------------------------------------------------------
// Handoff IA ⇄ humano
// ---------------------------------------------------------------------------
export async function handoffConversation(
  token: string,
  conversationId: string,
  to: "human" | "ia",
): Promise<HandoffResult> {
  const res = await authedFetch(token, `/conversations/${conversationId}/handoff`, {
    method: "POST",
    body: JSON.stringify({ to }),
  });

  if (res.status === 409) {
    let message = "Conversa já foi assumida por outro usuário.";
    let estado: string | null = null;
    let assumidoPor: string | null = null;
    try {
      const body = (await res.json()) as { detail?: unknown };
      const detail = body.detail;
      if (isRecord(detail)) {
        if (typeof detail.message === "string") message = detail.message;
        if (typeof detail.estado === "string") estado = detail.estado;
        if (typeof detail.assumidoPor === "string") assumidoPor = detail.assumidoPor;
      }
    } catch {
      /* mantém defaults */
    }
    throw new ConversationConflictError(message, estado, assumidoPor);
  }

  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível alternar o atendimento.");
  }
  return (await res.json()) as HandoffResult;
}

// ---------------------------------------------------------------------------
// Envio de resposta humana (US-13) — despacha pelo número oficial (WhatsApp)
// ---------------------------------------------------------------------------
export async function sendMessage(
  token: string,
  conversationId: string,
  texto: string,
): Promise<void> {
  const res = await authedFetch(token, `/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ texto }),
  });
  if (!res.ok) {
    // 409: assuma o atendimento / WhatsApp offline. 502: falha na Evolution.
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar a resposta.");
  }
}

export { ApiError, SessionExpiredError };
