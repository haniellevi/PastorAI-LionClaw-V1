/**
 * Cliente da conexão com o Google Agenda (módulo de Eventos, Fase 1).
 *
 * Contratos (app/routers/calendar.py) — todos admin-only, exceto o callback:
 *   GET    /calendar/status   -> { connected, calendarId }
 *   GET    /calendar/connect  -> { authUrl }   (redireciona o navegador ao Google)
 *   GET    /calendar/list     -> { calendars: [{ id, summary, primary }] }
 *   PUT    /calendar          -> { connected, calendarId }   (escolher a agenda)
 *   DELETE /calendar          -> 204                          (desconectar)
 */

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, readDetail } from "./dashboard-api";
import type { Role } from "./roles";

export interface CalendarStatus {
  connected: boolean;
  calendarId: string | null;
}

export interface CalendarOption {
  id: string;
  summary: string | null;
  primary: boolean;
}

/** Conectar/gerir a agenda é restrito ao papel admin (Configuração). */
export function canManageCalendar(roles: readonly Role[]): boolean {
  return roles.includes("admin");
}

export async function fetchCalendarStatus(token: string): Promise<CalendarStatus> {
  const res = await authedFetch(token, `/calendar/status`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a conexão da agenda.");
  }
  const d = (await res.json()) as { connected?: boolean; calendarId?: string | null };
  return { connected: Boolean(d.connected), calendarId: d.calendarId ?? null };
}

export async function fetchConnectUrl(token: string): Promise<string> {
  const res = await authedFetch(token, `/calendar/connect`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível iniciar a conexão com o Google.");
  }
  const d = (await res.json()) as { authUrl?: string };
  if (!d.authUrl) throw new ApiError(502, "O Google não retornou a URL de consentimento.");
  return d.authUrl;
}

export async function fetchCalendarList(token: string): Promise<CalendarOption[]> {
  const res = await authedFetch(token, `/calendar/list`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível listar as agendas.");
  }
  const d = (await res.json()) as { calendars?: CalendarOption[] };
  return d.calendars ?? [];
}

export async function selectCalendar(
  token: string,
  calendarId: string,
): Promise<CalendarStatus> {
  const res = await authedFetch(token, `/calendar`, {
    method: "PUT",
    body: JSON.stringify({ calendarId }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível selecionar a agenda.");
  }
  const d = (await res.json()) as { connected?: boolean; calendarId?: string | null };
  return { connected: Boolean(d.connected), calendarId: d.calendarId ?? null };
}

export async function disconnectCalendar(token: string): Promise<void> {
  const res = await authedFetch(token, `/calendar`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível desconectar a agenda.");
  }
}

// EVT-6 PR6.4 -------------------------------------------------------------
export interface ImportResult {
  created: number;
  skipped: number;
}

/**
 * Importa os eventos do Google da igreja (POST /calendar/import). O backend lê a
 * janela padrão (now→+90d), persiste como `a_confirmar`/`origem='google'` e
 * deduplica — nada é enviado. Os eventos aparecem na aba "A confirmar" da agenda.
 * 409 quando a agenda não está conectada.
 */
export async function importEvents(token: string): Promise<ImportResult> {
  const res = await authedFetch(token, `/calendar/import`, { method: "POST" });
  if (res.status === 409) {
    throw new ApiError(409, "Conecte a agenda do Google antes de importar.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível importar os eventos.");
  }
  const d = (await res.json()) as { created?: number; skipped?: number };
  return { created: d.created ?? 0, skipped: d.skipped ?? 0 };
}

// EVT-7 PR2 — destinatários de alerta da Agenda -----------------------------
/**
 * Destinatário de avisos internos da Agenda por WhatsApp (admin-only).
 * Contrato (app/routers/calendar.py, /calendar/recipients):
 *   GET    /calendar/recipients        -> { recipients: AlertRecipient[] }
 *   POST   /calendar/recipients        -> AlertRecipient   (409 se telefone dup ativo)
 *   PUT    /calendar/recipients/{id}   -> AlertRecipient   (parcial; 409 dup)
 *   DELETE /calendar/recipients/{id}   -> 204
 * Estes endpoints só CONFIGURAM — nada é enviado aqui.
 */
export interface AlertRecipient {
  id: string;
  nome: string;
  telefone: string;
  ativo: boolean;
}

export async function fetchAlertRecipients(token: string): Promise<AlertRecipient[]> {
  const res = await authedFetch(token, `/calendar/recipients`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os destinatários.");
  }
  const d = (await res.json()) as { recipients?: AlertRecipient[] };
  return d.recipients ?? [];
}

export async function createAlertRecipient(
  token: string,
  nome: string,
  telefone: string,
): Promise<AlertRecipient> {
  const res = await authedFetch(token, `/calendar/recipients`, {
    method: "POST",
    body: JSON.stringify({ nome, telefone }),
  });
  if (res.status === 409) {
    throw new ApiError(409, "Já existe um destinatário ativo com esse telefone.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível adicionar o destinatário.");
  }
  return (await res.json()) as AlertRecipient;
}

export async function updateAlertRecipient(
  token: string,
  id: string,
  patch: { nome?: string; telefone?: string; ativo?: boolean },
): Promise<AlertRecipient> {
  const res = await authedFetch(token, `/calendar/recipients/${id}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
  if (res.status === 409) {
    throw new ApiError(409, "Já existe um destinatário ativo com esse telefone.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível atualizar o destinatário.");
  }
  return (await res.json()) as AlertRecipient;
}

export async function deleteAlertRecipient(token: string, id: string): Promise<void> {
  const res = await authedFetch(token, `/calendar/recipients/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o destinatário.");
  }
}

export { ApiError, SessionExpiredError };
