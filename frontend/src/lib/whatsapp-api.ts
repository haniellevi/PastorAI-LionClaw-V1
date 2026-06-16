/**
 * Cliente da API de conexão WhatsApp (sprint Frontend Inbox & Conexão WhatsApp).
 * Consome o estado e o pareamento do número oficial (sprint-006).
 *
 * Contratos (SPEC 3.2 / app/routers/whatsapp.py):
 *   GET  /whatsapp/connection            -> { numero, status, ultimaSync }
 *   POST /whatsapp/connection {action}   -> { status, qr }
 *
 * Acesso (delta-005): telas de Configuração são admin-only; ambos os endpoints
 * exigem o papel `admin` no backend. Conectar/reconectar mantém 1 número por
 * igreja (RF-07); número já conectado retorna 409.
 */

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, readDetail } from "./dashboard-api";
import type { Role } from "./roles";

/** Estado do número oficial (espelha o enum do backend). */
export type ConnectionStatus = "online" | "offline" | "reconectando";

export interface ConnectionInfo {
  numero: string | null;
  status: ConnectionStatus;
  ultimaSync: string | null;
}

export interface ConnectResult {
  status: ConnectionStatus;
  qr: string | null;
}

/** Tela de conexão é restrita ao papel admin (delta-005 / US-05..07). */
export function canManageWhatsapp(roles: readonly Role[]): boolean {
  return roles.includes("admin");
}

/** Conflito RF-07: já existe um número conectado para a igreja. */
export class ConnectionConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConnectionConflictError";
  }
}

function normalizeStatus(value: unknown): ConnectionStatus {
  if (value === "online" || value === "reconectando") return value;
  return "offline";
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchConnection(token: string): Promise<ConnectionInfo> {
  const res = await authedFetch(token, `/whatsapp/connection`);
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à configuração do WhatsApp.");
  }
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a conexão do WhatsApp.");
  }
  const data = (await res.json()) as {
    numero?: string | null;
    status?: unknown;
    ultimaSync?: string | null;
  };
  return {
    numero: data.numero ?? null,
    status: normalizeStatus(data.status),
    ultimaSync: data.ultimaSync ?? null,
  };
}

// ---------------------------------------------------------------------------
// Conectar / reconectar
// ---------------------------------------------------------------------------
export async function connectWhatsapp(
  token: string,
  action: "connect" | "reconnect",
): Promise<ConnectResult> {
  const res = await authedFetch(token, `/whatsapp/connection`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });

  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new ConnectionConflictError(
      detail ?? "Já existe um número conectado para esta igreja.",
    );
  }
  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à configuração do WhatsApp.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível atualizar a conexão.");
  }
  const data = (await res.json()) as { status?: unknown; qr?: string | null };
  return { status: normalizeStatus(data.status), qr: data.qr ?? null };
}

// ---------------------------------------------------------------------------
// Desconectar (logout do aparelho)
// ---------------------------------------------------------------------------
/**
 * Desconecta (faz logout) do número oficial, mantendo a instância para um novo
 * pareamento. Usado para trocar o número/aparelho da igreja (US-06).
 */
export async function disconnectWhatsapp(token: string): Promise<ConnectResult> {
  const res = await authedFetch(token, `/whatsapp/connection`, {
    method: "POST",
    body: JSON.stringify({ action: "disconnect" }),
  });

  if (res.status === 403) {
    throw new ApiError(403, "Acesso restrito à configuração do WhatsApp.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível desconectar o número.");
  }
  const data = (await res.json()) as { status?: unknown; qr?: string | null };
  return { status: normalizeStatus(data.status), qr: data.qr ?? null };
}

export { ApiError, SessionExpiredError };
