/**
 * Cliente da API de comunicados segmentados (telas #comunicados e #central-celula).
 * Consome o backend (sprint-009):
 *
 *   GET  /broadcasts                  -> Page<BroadcastItem>     (histórico)
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

/** Resultado de POST /broadcasts. status=bloqueado quando alcance=0. */
export interface BroadcastResult {
  id: string;
  status: string; // enviado | agendado | bloqueado
  enviados: number;
  ignoradosOptout: number;
  agendadoPara: string | null;
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

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
export async function createBroadcast(
  token: string,
  input: CreateBroadcastInput,
): Promise<BroadcastResult> {
  const res = await authedFetch(token, `/broadcasts`, {
    method: "POST",
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
