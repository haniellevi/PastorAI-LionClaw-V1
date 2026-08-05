/**
 * Cliente da API de comunicados segmentados (telas #comunicados e #central-celula).
 * Consome o backend (sprint-009):
 *
 *   GET  /broadcasts                  -> Page<BroadcastItem>     (histórico)
 *   GET  /broadcasts/capabilities     -> BroadcastCapabilities  (rollout)
 *   POST /broadcasts {titulo,mensagem,segmentos,modo,agendamento?}
 *        -> { id, status, enviados, ignoradosOptout, agendadoPara }
 *
 * Regras de consentimento/opt-out são aplicadas no backend (RF-38): contatos
 * com opt-out ou sem consentimento são removidos do envio e contados em
 * `ignoradosOptout`. Quando o alcance limpo é zero, o envio é bloqueado
 * (status=bloqueado, enviados=0) — a UI reflete o bloqueio com a contagem de
 * ignorados. Os tokens de segmento espelham os reconhecidos pelo backend
 * (`todos` + pessoa.tipo).
 */

import {
  ApiError,
  authedFetch,
  readDetail,
  type Page,
} from "./dashboard-api";
import type { Contact } from "./contacts-api";

export type { Page } from "./dashboard-api";

/** Comunicado retornado por GET /broadcasts (histórico). */
export interface BroadcastItem {
  id: string;
  titulo: string;
  mensagem: string;
  segmentos: string[];
  modo: string;
  status: string | null; // enviado | agendado | rascunho
  alcance: number | null;
  ignoradosOptout: number | null;
  data: string | null;
  hora: string | null;
  repeticao: string | null;
  proximaExecucao: string | null;
  precisaRevisao: boolean;
  resultadoUltimaExecucao: string | null;
  entregasAceitas: number;
  entregasFalhas: number;
  entregasDesconhecidas: number;
  entregasSuprimidas: number;
  entregasPendentes: number;
}

export type BroadcastRepeat = "once" | "daily" | "weekly" | "biweekly" | "monthly";

export interface BroadcastSchedule {
  data: string; // YYYY-MM-DD
  hora?: string | null;
  repeticao?: BroadcastRepeat | null;
}

export interface CreateBroadcastInput {
  titulo: string;
  mensagem: string;
  segmentos: string[];
  modo: "agora" | "agendado";
  agendamento?: BroadcastSchedule | null;
}

/** Resultado de POST /broadcasts. O 202 assíncrono retorna status=enfileirado. */
export interface BroadcastResult {
  id: string;
  status: string; // enviado | agendado | enfileirado | bloqueado
  enviados: number;
  ignoradosOptout: number;
  agendadoPara: string | null;
  execucaoId: string | null;
  alcancePrevisto: number | null;
}

/** Disponibilidade operacional controlada pelo backend/worker. */
export interface BroadcastCapabilities {
  agendamentoDisponivel: boolean;
  motivo: "despacho_indisponivel" | "envios_externos_desabilitados" | null;
}

export interface BroadcastResultFeedback {
  kind: "ok" | "err";
  text: string;
}

/** Human feedback that never presents an adverse ledger result as success. */
export function broadcastResultFeedback(
  result: BroadcastResult,
): BroadcastResultFeedback {
  switch (result.status) {
    case "agendado":
      return {
        kind: "ok",
        text: `Comunicado agendado. ${result.ignoradosOptout} ignorado(s) por opt-out.`,
      };
    case "enfileirado":
      return {
        kind: "ok",
        text: `Comunicado enfileirado para ${result.alcancePrevisto ?? 0} contato(s). O histórico será atualizado após o processamento.`,
      };
    case "enviado":
      return {
        kind: "ok",
        text: `Comunicado enviado a ${result.enviados} contato(s). ${result.ignoradosOptout} ignorado(s).`,
      };
    case "parcial":
      return {
        kind: "err",
        text: `Comunicado concluído parcialmente: ${result.enviados} envio(s) aceito(s). Consulte o histórico.`,
      };
    case "falhou":
      return { kind: "err", text: "O comunicado falhou. Consulte o histórico antes de tentar novamente." };
    case "desconhecido":
      return { kind: "err", text: "O resultado do comunicado é desconhecido. Não reenvie antes de conferir o histórico." };
    case "suprimido":
      return { kind: "err", text: "O comunicado foi suprimido pelas travas de segurança e não foi enviado." };
    case "concluido_sem_destinatarios":
      return { kind: "err", text: "O comunicado foi concluído sem destinatários elegíveis." };
    default:
      return { kind: "err", text: "O comunicado terminou com um resultado inesperado. Consulte o histórico." };
  }
}

/** Definição de um segmento selecionável (token reconhecido pelo backend). */
export interface SegmentDef {
  token: string;
  label: string;
  helper?: string;
}

/** Segmentos disponíveis no compositor (tokens: todos + pessoa.tipo). */
export const SEGMENTS: SegmentDef[] = [
  { token: "todos", label: "Todos os contatos com consentimento" },
  { token: "visitante", label: "Visitantes" },
  { token: "discipulo", label: "Discípulos em consolidação" },
  { token: "lider", label: "Líderes de célula" },
  { token: "membro", label: "Membros" },
  { token: "pastor", label: "Pastores" },
];

const REPEAT_LABEL: Record<BroadcastRepeat, string> = {
  once: "Não repetir (uma vez)",
  daily: "Diariamente",
  weekly: "Semanalmente",
  biweekly: "Quinzenalmente",
  monthly: "Mensalmente",
};

export function repeatLabel(repeticao: string | null | undefined): string {
  if (!repeticao) return REPEAT_LABEL.once;
  return REPEAT_LABEL[repeticao as BroadcastRepeat] ?? repeticao;
}

/** True quando o contato pertence a algum dos segmentos selecionados. */
export function matchesSegments(contact: Contact, tokens: string[]): boolean {
  if (tokens.includes("todos")) return true;
  const tipo = (contact.tipo ?? "").trim().toLowerCase();
  return tipo.length > 0 && tokens.includes(tipo);
}

/** Contatos alcançados (estimativa) pelos segmentos selecionados. */
export function resolveRecipients(contacts: Contact[], tokens: string[]): Contact[] {
  if (tokens.length === 0) return [];
  return contacts.filter((c) => matchesSegments(c, tokens));
}

/** Contagem de pessoas por segmento (estimativa client-side por tipo). */
export function countSegment(contacts: Contact[], token: string): number {
  if (token === "todos") return contacts.length;
  return contacts.filter((c) => (c.tipo ?? "").trim().toLowerCase() === token).length;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchBroadcasts(
  token: string,
  pageSize = 100,
): Promise<Page<BroadcastItem>> {
  const res = await authedFetch(token, `/broadcasts?page=1&pageSize=${pageSize}`);
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à comunicação da igreja.");
  }
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar os comunicados.");
  }
  return (await res.json()) as Page<BroadcastItem>;
}

export async function fetchBroadcastCapabilities(
  token: string,
): Promise<BroadcastCapabilities> {
  const res = await authedFetch(token, `/broadcasts/capabilities`);
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à comunicação da igreja.");
  }
  if (!res.ok) {
    throw new ApiError(
      res.status,
      "Não foi possível confirmar a disponibilidade dos envios.",
    );
  }
  return (await res.json()) as BroadcastCapabilities;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
export async function createBroadcast(
  token: string,
  input: CreateBroadcastInput,
  idempotencyKey: string,
): Promise<BroadcastResult> {
  const res = await authedFetch(token, `/broadcasts`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      titulo: input.titulo,
      mensagem: input.mensagem,
      segmentos: input.segmentos,
      modo: input.modo,
      agendamento: input.agendamento
        ? {
            data: input.agendamento.data,
            hora: input.agendamento.hora ?? null,
            repeticao: input.agendamento.repeticao ?? null,
          }
        : null,
    }),
  });
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à comunicação da igreja.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar o comunicado.");
  }
  return (await res.json()) as BroadcastResult;
}
