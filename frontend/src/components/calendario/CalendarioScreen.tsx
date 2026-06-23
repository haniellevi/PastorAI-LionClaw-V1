"use client";

/**
 * Tela #calendario — agenda da igreja em calendar-month, sincronizada com o
 * Google Calendar (api-events). Cria evento (form-field/btn-primary) e o mostra
 * no mês. Falha de sync / token Google expirado exibe o banner "calendário
 * desconectado" com CTA reconectar, mantendo os eventos locais; eventos salvos
 * sem sincronizar ficam marcados como "não sincronizado" com re-tentar.
 *
 * Estados: loading (skeleton) · empty (sem eventos no mês) · populated.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CalendarConnectCard } from "@/components/calendario/CalendarConnectCard";
import { EventFormModal } from "@/components/calendario/EventFormModal";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  buildMonthGrid,
  createEvent,
  eventsInMonth,
  fetchEvents,
  monthLabel,
  type CreateEventInput,
  type EventItem,
} from "@/lib/events-api";
import { Icon } from "@/lib/icons";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

export function CalendarioScreen() {
  const { token, expireSession } = useAuth();
  const today = useMemo(() => new Date(), []);

  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await fetchEvents(token);
        setEvents(page.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar a agenda.");
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3600);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const monthEvents = useMemo(() => eventsInMonth(events, year, month), [events, year, month]);
  const cells = useMemo(
    () => buildMonthGrid(year, month, monthEvents, today),
    [year, month, monthEvents, today],
  );
  const unsynced = useMemo(() => events.filter((e) => !e.sincronizado), [events]);
  const disconnected = unsynced.length > 0;

  const goPrev = useCallback(() => {
    setMonth((m) => {
      if (m === 0) {
        setYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  }, []);
  const goNext = useCallback(() => {
    setMonth((m) => {
      if (m === 11) {
        setYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  }, []);

  const handleCreate = useCallback(
    async (input: CreateEventInput) => {
      if (!token) return;
      setSaving(true);
      setFormError(null);
      try {
        const created = await createEvent(token, input);
        setEvents((prev) => [...prev, created]);
        setShowForm(false);
        // Pula para o mês do evento criado para que apareça no grid.
        const [y, m] = created.data.split("-").map(Number);
        if (y != null && m != null && !Number.isNaN(y) && !Number.isNaN(m)) {
          setYear(y);
          setMonth(m - 1);
        }
        flashToast({
          kind: created.sincronizado ? "ok" : "err",
          text: created.sincronizado
            ? `Evento "${created.titulo}" criado e sincronizado.`
            : `Evento "${created.titulo}" salvo localmente, mas não sincronizado com o Google.`,
        });
      } catch (err) {
        if (handleSessionError(err)) return;
        setFormError(err instanceof ApiError ? err.message : "Não foi possível salvar o evento.");
      } finally {
        setSaving(false);
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleReconnect = useCallback(async () => {
    setReconnecting(true);
    try {
      await load("retry");
      flashToast({ kind: "ok", text: "Tentando reconectar com o Google Calendar…" });
    } finally {
      setReconnecting(false);
    }
  }, [load, flashToast]);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="calendario">
      <div className="screen-head">
        <div className="titles">
          <h2>Calendário · {monthLabel(year, month)}</h2>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-sm" onClick={goPrev} aria-label="Mês anterior">
            <Icon name="chevron-left" />
          </button>
          <button type="button" className="btn btn-sm" onClick={goNext} aria-label="Próximo mês">
            <Icon name="caret" />
          </button>
          <button type="button" className="btn btn-primary" onClick={() => { setFormError(null); setShowForm(true); }}>
            <Icon name="plus" />
            <span>Novo evento</span>
          </button>
        </div>
      </div>

      <CalendarConnectCard />

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {disconnected ? (
        <div className="degraded-banner" role="alert" style={{ borderRadius: "var(--r-md)", marginBottom: "var(--s3)" }}>
          <Icon name="alert" />
          <span>
            Calendário desconectado: {unsynced.length} evento(s) não sincronizado(s)
            com o Google. Os eventos locais foram preservados.
          </span>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => void handleReconnect()}
            disabled={reconnecting}
            style={{ marginLeft: "auto" }}
          >
            {reconnecting ? "Reconectando…" : "Reconectar"}
          </button>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="card card-pad">
          <div className="sk-line sk-lg" />
          <div className="sk-line sk-md" />
          <div className="sk-line sk-sm" />
        </div>
      ) : (
        <>
          <div className="cal">
            <div className="cal-head">
              {WEEKDAYS.map((d) => (
                <div key={d}>{d}</div>
              ))}
            </div>
            <div className="cal-grid">
              {cells.map((cell, i) => (
                <div
                  key={cell.iso ?? `pad-${i}`}
                  className={`cal-cell${cell.day == null ? " off" : ""}${cell.today ? " today" : ""}`}
                >
                  {cell.day != null ? <div className="d num">{cell.day}</div> : null}
                  {cell.events.map((ev) => (
                    <div
                      key={ev.id}
                      className={`cal-ev${ev.sincronizado ? "" : " warn"}`}
                      title={ev.sincronizado ? ev.titulo : `${ev.titulo} · não sincronizado`}
                    >
                      {ev.hora ? `${ev.hora} ` : ""}
                      {ev.titulo}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          {monthEvents.length === 0 ? (
            <div className="card" style={{ marginTop: "var(--s4)" }}>
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="calendar" />
                <p>
                  <strong>Nenhum evento em {monthLabel(year, month)}.</strong> Crie
                  o primeiro evento para aparecer no calendário.
                </p>
              </div>
            </div>
          ) : null}

          {unsynced.length > 0 ? (
            <div className="card" style={{ marginTop: "var(--s4)" }}>
              <div className="panel-title" style={{ color: "var(--warn)" }}>
                <Icon name="alert" /> Eventos não sincronizados
                <span className="count">· {unsynced.length}</span>
              </div>
              {unsynced.map((ev) => (
                <div className="list-row" key={ev.id}>
                  <div style={{ flex: 1 }}>
                    <div className="nm">{ev.titulo}</div>
                    <div className="sub">{ev.data}{ev.hora ? ` · ${ev.hora}` : ""}</div>
                  </div>
                  <span className="pill warn">Não sincronizado</span>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => void load("retry")}
                    disabled={loading}
                  >
                    Re-tentar
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}

      {showForm ? (
        <EventFormModal
          busy={saving}
          error={formError}
          onClose={() => {
            setShowForm(false);
            setFormError(null);
          }}
          onSubmit={(input) => void handleCreate(input)}
        />
      ) : null}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
