"use client";

/**
 * Card "Conexão com o Google Agenda" — módulo de Eventos, Fase 1.
 *
 * Admin-only (retorna null para os demais). Mostra o estado da conexão, inicia
 * o OAuth (redireciona ao Google), deixa o admin escolher qual agenda usar e
 * permite desconectar. A sincronização de eventos em si vem nas Fases 2/3.
 */
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  SessionExpiredError,
  canManageCalendar,
  disconnectCalendar,
  fetchCalendarList,
  fetchCalendarStatus,
  fetchConnectUrl,
  importEvents,
  selectCalendar,
  type CalendarOption,
  type ImportResult,
} from "@/lib/calendar-api";
import { Icon } from "@/lib/icons";

interface CalendarConnectCardProps {
  /** EVT-6 PR6.4: chamado após importar do Google (a agenda recarrega a lista). */
  onImported?: (result: ImportResult) => void;
}

export function CalendarConnectCard({ onImported }: CalendarConnectCardProps) {
  const { user, token, expireSession } = useAuth();
  const isAdmin = user ? canManageCalendar(user.roles) : false;

  const [connected, setConnected] = useState(false);
  const [calendarId, setCalendarId] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<CalendarOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onErr = useCallback(
    (e: unknown) => {
      if (e instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(e instanceof ApiError ? e.message : "Não foi possível falar com a agenda.");
    },
    [expireSession],
  );

  const loadStatus = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const s = await fetchCalendarStatus(token);
      setConnected(s.connected);
      setCalendarId(s.calendarId);
      if (s.connected) {
        try {
          setCalendars(await fetchCalendarList(token));
        } catch {
          /* a lista é best-effort: a conexão segue válida sem ela */
        }
      }
    } catch (e) {
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, onErr]);

  useEffect(() => {
    if (isAdmin) void loadStatus();
    else setLoading(false);
  }, [isAdmin, loadStatus]);

  const connect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const url = await fetchConnectUrl(token);
      window.location.href = url; // redireciona ao consentimento do Google
    } catch (e) {
      onErr(e);
      setBusy(false);
    }
  }, [token, onErr]);

  const pick = useCallback(
    async (id: string) => {
      if (!token || !id) return;
      setBusy(true);
      setError(null);
      try {
        const s = await selectCalendar(token, id);
        setCalendarId(s.calendarId);
      } catch (e) {
        onErr(e);
      } finally {
        setBusy(false);
      }
    },
    [token, onErr],
  );

  const runImport = useCallback(async () => {
    if (!token) return;
    setImporting(true);
    setError(null);
    try {
      const result = await importEvents(token);
      onImported?.(result);
    } catch (e) {
      onErr(e);
    } finally {
      setImporting(false);
    }
  }, [token, onErr, onImported]);

  const disconnect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectCalendar(token);
      setConnected(false);
      setCalendarId(null);
      setCalendars([]);
    } catch (e) {
      onErr(e);
    } finally {
      setBusy(false);
    }
  }, [token, onErr]);

  if (!isAdmin || loading) return null;

  return (
    <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
      <div className="panel-title">
        <Icon name="calendar" /> Conexão com o Google Agenda
      </div>

      {error ? (
        <p className="sub" style={{ color: "var(--danger)", marginTop: "var(--s2)" }}>
          {error}
        </p>
      ) : null}

      {!connected ? (
        <>
          <p className="sub" style={{ color: "var(--muted)", margin: "var(--s2) 0 var(--s3)" }}>
            Conecte a agenda do Google da igreja para sincronizar os eventos.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void connect()}
            disabled={busy}
          >
            <Icon name="calendar" />
            <span>{busy ? "Abrindo o Google…" : "Conectar Google Agenda"}</span>
          </button>
        </>
      ) : (
        <>
          <div className="conn-row" style={{ marginTop: "var(--s2)" }}>
            <span style={{ color: "var(--muted)" }}>Agenda sincronizada</span>
            <span className="pill accent">{calendarId ?? "selecione abaixo"}</span>
          </div>

          {calendars.length > 0 ? (
            <label style={{ display: "block", marginTop: "var(--s3)" }}>
              <span className="sub" style={{ color: "var(--muted)" }}>Escolha a agenda</span>
              <select
                className="input"
                value={calendarId ?? ""}
                onChange={(e) => void pick(e.target.value)}
                disabled={busy}
                style={{ display: "block", marginTop: "var(--s1)", width: "100%" }}
              >
                <option value="" disabled>
                  Selecione…
                </option>
                {calendars.map((c) => (
                  <option key={c.id} value={c.id}>
                    {(c.summary ?? c.id) + (c.primary ? " (principal)" : "")}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div style={{ display: "flex", gap: 8, marginTop: "var(--s4)" }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void runImport()}
              disabled={busy || importing}
            >
              <Icon name="download" />
              <span>{importing ? "Importando…" : "Importar eventos do Google"}</span>
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => void disconnect()}
              disabled={busy || importing}
            >
              <Icon name="logout" />
              <span>Desconectar</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
