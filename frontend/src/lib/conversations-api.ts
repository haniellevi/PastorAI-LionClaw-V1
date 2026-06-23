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
  /** Nome de quem assumiu o atendimento (humano). null quando IA/aguardando. */
  assumidoPorNome: string | null;
  assumidoEm: string | null;
  esperaDesde: string | null;
  atualizadoEm: string | null;
  /** Tipo da pessoa vinculada (marca discreta no chat). null sem cadastro. */
  tipo: string | null;
  /** CSIM (sem interesse ministerial) da pessoa vinculada. */
  semInteresse: boolean;
}

/** Tipo do conteúdo de uma mensagem (Etapa 2 — mídia). */
export type ChatMessageTipo = "texto" | "imagem" | "arquivo" | "audio";

/** Uma mensagem do histórico da conversa (GET /conversations/{id}/messages). */
export interface ChatMessage {
  id: string;
  direcao: "in" | "out";
  autor: "contato" | "ia" | "humano";
  /** Nome de quem respondeu (humano). null para IA/contato. */
  autorNome: string | null;
  tipo: ChatMessageTipo;
  texto: string | null;
  /** URL assinada de curta duração para a mídia (imagem/arquivo/áudio). */
  mediaUrl: string | null;
  mediaMime: string | null;
  mediaNome: string | null;
  criadoEm: string;
}

export interface HandoffResult {
  estado: string;
  assumidoPor: string | null;
}

/**
 * Papéis privilegiados do inbox (US-11). Espelha INBOX_ROLES do backend
 * (app/domain/conversations.py): admin passa implicitamente; pastor, lider_g12
 * e operador têm acesso. Líder de célula/membro nunca acessam.
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

/** Histórico completo da conversa, mais antigas primeiro (US-13). */
export async function fetchMessages(
  token: string,
  conversationId: string,
  pageSize = 200,
): Promise<ChatMessage[]> {
  const res = await authedFetch(
    token,
    `/conversations/${conversationId}/messages?page=1&pageSize=${pageSize}`,
  );
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito ao inbox.");
  }
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as mensagens.");
  }
  const page = (await res.json()) as Page<ChatMessage>;
  return page.items;
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

// ---------------------------------------------------------------------------
// Envio de mídia (Etapa 2) — imagem/arquivo pelo número oficial (WhatsApp)
// ---------------------------------------------------------------------------
/** Lê um File e devolve o base64 puro (sem o prefixo `data:...;base64,`). */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Falha ao ler o arquivo."));
        return;
      }
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(new Error("Falha ao ler o arquivo."));
    reader.readAsDataURL(file);
  });
}

/**
 * Envia uma imagem/arquivo ao contato pelo número oficial (Etapa 2). O arquivo
 * é lido como base64 e enviado em JSON (sem multipart). Mesmas regras do envio
 * de texto: é preciso ter assumido o atendimento e o WhatsApp estar online.
 */
export async function sendMedia(
  token: string,
  conversationId: string,
  file: File,
  caption?: string,
): Promise<ChatMessage> {
  const base64 = await fileToBase64(file);
  const res = await authedFetch(token, `/conversations/${conversationId}/messages/media`, {
    method: "POST",
    body: JSON.stringify({
      mime: file.type || "application/octet-stream",
      base64,
      nome: file.name || null,
      caption: caption && caption.trim() ? caption.trim() : null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar a mídia.");
  }
  return (await res.json()) as ChatMessage;
}

// ---------------------------------------------------------------------------
// Exclusão de conversa (hard delete — admin)
// ---------------------------------------------------------------------------
/**
 * Exclui permanentemente uma conversa (mensagens + mídia). Ação destrutiva e
 * restrita ao admin no backend (403 caso contrário); 204 no sucesso.
 */
export async function deleteConversation(
  token: string,
  conversationId: string,
): Promise<void> {
  const res = await authedFetch(token, `/conversations/${conversationId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível excluir a conversa.");
  }
}

// ---------------------------------------------------------------------------
// Marcar como lida (zera o contador ao abrir a conversa)
// ---------------------------------------------------------------------------
export async function markConversationRead(
  token: string,
  conversationId: string,
): Promise<void> {
  const res = await authedFetch(token, `/conversations/${conversationId}/read`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível marcar como lida.");
  }
}

// ---------------------------------------------------------------------------
// Transferir o atendimento para outro membro
// ---------------------------------------------------------------------------
export interface TransferResult {
  estado: string;
  assumidoPor: string | null;
  assumidoPorNome: string | null;
}

/**
 * Transfere o atendimento humano para outro usuário com acesso ao inbox. Admin
 * transfere qualquer conversa; o detentor atual transfere a que está atendendo
 * (409 caso contrário). 422 se o destino não tiver acesso ao inbox.
 */
export async function transferConversation(
  token: string,
  conversationId: string,
  toUserId: string,
): Promise<TransferResult> {
  const res = await authedFetch(token, `/conversations/${conversationId}/transfer`, {
    method: "POST",
    body: JSON.stringify({ toUserId }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível transferir a conversa.");
  }
  return (await res.json()) as TransferResult;
}

// ---------------------------------------------------------------------------
// Foto de perfil do contato (Etapa 4) — best-effort, pode ser null
// ---------------------------------------------------------------------------
export async function fetchConversationPhoto(
  token: string,
  conversationId: string,
): Promise<string | null> {
  const res = await authedFetch(token, `/conversations/${conversationId}/photo`);
  if (!res.ok) return null;
  const body = (await res.json()) as { url?: string | null };
  return body.url ?? null;
}

export { ApiError, SessionExpiredError };
