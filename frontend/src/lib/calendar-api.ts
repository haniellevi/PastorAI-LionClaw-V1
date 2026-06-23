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

export { ApiError, SessionExpiredError };
