/**
 * Formatação/derivações puras das conversas do inbox (sem I/O) — testável e
 * compartilhada entre a lista e a thread.
 */
import type { Conversation, ConversationEstado } from "@/lib/conversations-api";

/** Estado efetivo da conversa: a fila de espera (espera_desde) tem prioridade. */
export function effectiveEstado(c: Conversation): ConversationEstado {
  if (c.estado === "humano") return "humano";
  if (c.estado === "aguardando" || c.esperaDesde) return "aguardando";
  return "ia";
}

/** Pílula de status da conversa (tone + rótulo) por estado efetivo. */
export function estadoPill(estado: ConversationEstado): {
  tone: "ok" | "warn" | "accent";
  label: string;
} {
  if (estado === "humano") return { tone: "ok", label: "Em atendimento" };
  if (estado === "aguardando") return { tone: "warn", label: "Aguardando humano" };
  return { tone: "accent", label: "IA ativa" };
}

/**
 * Máscara parcial do telefone para privacidade (RNF): mantém o início e os
 * quatro últimos dígitos, ocultando o miolo.
 */
export function maskPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 7) return raw;
  const head = digits.slice(0, digits.length > 11 ? 4 : 2);
  const tail = digits.slice(-4);
  return `+${head} •••• ${tail}`;
}

/** Avatar textual a partir do telefone (dois últimos dígitos). */
export function phoneAvatar(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  return digits.slice(-2) || "WA";
}

/**
 * Nome de exibição do contato: usa o nome real quando o contato está
 * cadastrado/vinculado; senão cai no telefone mascarado (privacidade).
 */
export function displayName(c: Conversation): string {
  const nome = c.nome?.trim();
  return nome ? nome : maskPhone(c.telefone);
}

/** Iniciais do nome para o avatar; sem nome, usa os dígitos do telefone. */
export function contactAvatar(c: Conversation): string {
  const nome = c.nome?.trim();
  if (!nome) return phoneAvatar(c.telefone);
  const parts = nome.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || phoneAvatar(c.telefone);
}

/** Horário curto (HH:MM) ou "Ontem"/data para o carimbo da lista. */
export function shortTime(iso: string | null, now: number): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const date = new Date(ts);
  const today = new Date(now);
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate();
  if (sameDay) {
    return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const isYesterday =
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate();
  if (isYesterday) return "Ontem";
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}
