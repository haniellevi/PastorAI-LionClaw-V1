"use client";

/**
 * Tela #calendario — Agenda da igreja (EVT-3). Lê eventos reais de GET /events e
 * oferece três visões: Semana, Mês e Ano.
 *  - Semana: lista vertical dos 7 dias (Dom→Sáb) da semana em foco, eventos por
 *    dia. Lista (não 7 colunas) → legível no mobile, sem overflow horizontal.
 *  - Mês: grade mensal (calendar-month) com os eventos reais do mês.
 *  - Ano: grade compacta dos 12 meses, cada um com contagem + prévia; clicar abre
 *    o mês.
 * Eventos com recorrencia='semanal' não têm data fixa (EVT-1, `data=null`) e
 * `dia_semana` não é exposto no EventOut — então não entram no grid: vão para a
 * seção "Eventos recorrentes". A navegação usa um cursor (Date) deslocado pela
 * unidade da visão atual.
 *
 * A criação manual de evento (EventFormModal) e a UX de sync com o Google
 * (banner desconectado / re-tentar) são preservadas como estavam.
 *
 * Estados: loading (skeleton) · empty (sem eventos na visão) · populated.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { CalendarConnectCard } from "@/components/calendario/CalendarConnectCard";
import { EventDetailModal } from "@/components/calendario/EventDetailModal";
import { EventFormModal } from "@/components/calendario/EventFormModal";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  buildMonthGrid,
  buildWeekDays,
  buildYearMonths,
  confirmEvent,
  createEvent,
  dateFromIso,
  deleteEvent,
  eventsInMonth,
  fetchEvents,
  partitionEvents,
  shiftCursor,
  updateEvent,
  viewLabel,
  type CreateEventInput,
  type EventItem,
  type EventView,
} from "@/lib/events-api";
import { Icon } from "@/lib/icons";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const VIEWS: { id: EventView; label: string }[] = [
  { id: "semana", label: "Semana" },
  { id: "mes", label: "Mês" },
  { id: "ano", label: "Ano" },
];
const PREV_LABEL: Record<EventView, string> = {
  semana: "Semana anterior",
  mes: "Mês anterior",
  ano: "Ano anterior",
};
const NEXT_LABEL: Record<EventView, string> = {
  semana: "Próxima semana",
  mes: "Próximo mês",
  ano: "Próximo ano",
};

export function CalendarioScreen() {
  const { token, expireSession } = useAuth();
  const today = useMemo(() => new Date(), []);

  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<EventView>("mes");
  const [cursor, setCursor] = useState<Date>(() => new Date());

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  // EVT-4: detalhe / edição / exclusão. `selected` abre o detalhe; `editing`
  // abre o form em modo edição. `mut*` cobrem excluir/confirmar (ações do detalhe).
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [editing, setEditing] = useState<EventItem | null>(null);
  const [mutBusy, setMutBusy] = useState(false);
  const [mutError, setMutError] = useState<string | null>(null);

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

  // Eventos com data fixa alimentam os grids; recorrentes (data=null) vão à
  // seção própria e são excluídos da heurística de "não sincronizado".
  const { dated, recurring } = useMemo(() => partitionEvents(events), [events]);

  const year = cursor.getFullYear();
  const month = cursor.getMonth();

  const monthEvents = useMemo(
    () => (view === "mes" ? eventsInMonth(dated, year, month) : []),
    [view, dated, year, month],
  );
  const monthCells = useMemo(
    () => (view === "mes" ? buildMonthGrid(year, month, monthEvents, today) : []),
    [view, year, month, monthEvents, today],
  );
  const weekDays = useMemo(
    () => (view === "semana" ? buildWeekDays(cursor, dated, today) : []),
    [view, cursor, dated, today],
  );
  const yearMonths = useMemo(
    () => (view === "ano" ? buildYearMonths(year, dated, today) : []),
    [view, year, dated, today],
  );

  const viewIsEmpty =
    (view === "mes" && monthEvents.length === 0) ||
    (view === "semana" && weekDays.every((d) => d.events.length === 0)) ||
    (view === "ano" && yearMonths.every((m) => m.count === 0));

  const unsynced = useMemo(() => dated.filter((e) => !e.sincronizado), [dated]);
  const disconnected = unsynced.length > 0;

  const goPrev = useCallback(() => setCursor((c) => shiftCursor(c, view, -1)), [view]);
  const goNext = useCallback(() => setCursor((c) => shiftCursor(c, view, 1)), [view]);
  const goToday = useCallback(() => setCursor(new Date()), []);

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
        if (created.data) {
          setCursor(dateFromIso(created.data));
          setView("mes");
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

  // EVT-4 ---------------------------------------------------------------------
  const replaceEvent = useCallback((updated: EventItem) => {
    setEvents((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
  }, []);

  const openDetail = useCallback((ev: EventItem) => {
    setMutError(null);
    setSelected(ev);
  }, []);

  /** Props para tornar um item de evento clicável/acessível (abre o detalhe). */
  const eventActivation = useCallback(
    (ev: EventItem) => ({
      role: "button" as const,
      tabIndex: 0,
      style: { cursor: "pointer" as const },
      onClick: () => openDetail(ev),
      onKeyDown: (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDetail(ev);
        }
      },
    }),
    [openDetail],
  );

  const handleEdit = useCallback(
    async (input: CreateEventInput) => {
      if (!token || !editing) return;
      setSaving(true);
      setFormError(null);
      try {
        const updated = await updateEvent(token, editing.id, input);
        replaceEvent(updated);
        setEditing(null);
        flashToast({ kind: "ok", text: `Evento "${updated.titulo}" atualizado.` });
      } catch (err) {
        if (handleSessionError(err)) return;
        setFormError(err instanceof ApiError ? err.message : "Não foi possível salvar as alterações.");
      } finally {
        setSaving(false);
      }
    },
    [token, editing, replaceEvent, flashToast, handleSessionError],
  );

  const handleDelete = useCallback(async () => {
    if (!token || !selected) return;
    setMutBusy(true);
    setMutError(null);
    try {
      await deleteEvent(token, selected.id);
      setEvents((prev) => prev.filter((e) => e.id !== selected.id));
      flashToast({ kind: "ok", text: `Evento "${selected.titulo}" excluído.` });
      setSelected(null);
    } catch (err) {
      if (handleSessionError(err)) return;
      setMutError(err instanceof ApiError ? err.message : "Não foi possível excluir o evento.");
    } finally {
      setMutBusy(false);
    }
  }, [token, selected, flashToast, handleSessionError]);

  const handleConfirm = useCallback(async () => {
    if (!token || !selected) return;
    setMutBusy(true);
    setMutError(null);
    try {
      const updated = await confirmEvent(token, selected.id);
      replaceEvent(updated);
      setSelected(updated);
      flashToast({ kind: "ok", text: `Evento "${updated.titulo}" confirmado.` });
    } catch (err) {
      if (handleSessionError(err)) return;
      setMutError(err instanceof ApiError ? err.message : "Não foi possível confirmar o evento.");
    } finally {
      setMutBusy(false);
    }
  }, [token, selected, replaceEvent, flashToast, handleSessionError]);

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
  const periodLabel = viewLabel(cursor, view);

  return (
    <div className="screen" key="calendario">
      <div className="screen-head">
        <div className="titles">
          <h2>Calendário · {periodLabel}</h2>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-sm" onClick={goToday}>
            Hoje
          </button>
          <button type="button" className="btn btn-sm" onClick={goPrev} aria-label={PREV_LABEL[view]}>
            <Icon name="chevron-left" />
          </button>
          <button type="button" className="btn btn-sm" onClick={goNext} aria-label={NEXT_LABEL[view]}>
            <Icon name="caret" />
          </button>
          <button type="button" className="btn btn-primary" onClick={() => { setFormError(null); setShowForm(true); }}>
            <Icon name="plus" />
            <span>Novo evento</span>
          </button>
        </div>
      </div>

      <div className="tabs agenda-tabs" role="tablist" aria-label="Visualização da agenda">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={view === v.id}
            className={`tab${view === v.id ? " active" : ""}`}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
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
          {view === "mes" ? (
            <div className="cal">
              <div className="cal-head">
                {WEEKDAYS.map((d) => (
                  <div key={d}>{d}</div>
                ))}
              </div>
              <div className="cal-grid">
                {monthCells.map((cell, i) => (
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
                        {...eventActivation(ev)}
                      >
                        {ev.hora ? `${ev.hora} ` : ""}
                        {ev.titulo}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {view === "semana" ? (
            <div className="agenda-week">
              {weekDays.map((d) => (
                <div key={d.iso} className={`agenda-day${d.today ? " today" : ""}`}>
                  <div className="agenda-day-head">
                    <span className="wd">{WEEKDAYS[d.weekday]}</span>
                    <span className="dt">{d.day} {d.monthShort}{d.today ? " · hoje" : ""}</span>
                  </div>
                  {d.events.length ? (
                    <div className="agenda-day-evs">
                      {d.events.map((ev) => (
                        <div
                          key={ev.id}
                          className={`cal-ev${ev.sincronizado ? "" : " warn"}`}
                          title={ev.sincronizado ? ev.titulo : `${ev.titulo} · não sincronizado`}
                          {...eventActivation(ev)}
                        >
                          {ev.hora ? `${ev.hora} · ` : ""}
                          {ev.titulo}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="agenda-day-empty">—</div>
                  )}
                </div>
              ))}
            </div>
          ) : null}

          {view === "ano" ? (
            <div className="agenda-year">
              {yearMonths.map((mo) => (
                <button
                  key={mo.month}
                  type="button"
                  className={`agenda-month${mo.isCurrent ? " current" : ""}`}
                  onClick={() => { setCursor(new Date(year, mo.month, 1)); setView("mes"); }}
                  aria-label={`Abrir ${mo.label} de ${year}`}
                >
                  <div className="agenda-month-head">
                    <span className="mn">{mo.label}</span>
                    <span className="count">{mo.count}</span>
                  </div>
                  {mo.count ? (
                    <ul className="agenda-month-list">
                      {mo.events.slice(0, 3).map((ev) => (
                        <li key={ev.id}>
                          <span className="dot" />
                          {ev.data ? `${Number(ev.data.slice(8, 10))} ` : ""}
                          {ev.titulo}
                        </li>
                      ))}
                      {mo.count > 3 ? <li className="more">+{mo.count - 3} mais</li> : null}
                    </ul>
                  ) : (
                    <div className="agenda-month-empty">Sem eventos</div>
                  )}
                </button>
              ))}
            </div>
          ) : null}

          {viewIsEmpty ? (
            <div className="card" style={{ marginTop: "var(--s4)" }}>
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="calendar" />
                <p>
                  <strong>Nenhum evento em {periodLabel}.</strong> Use as setas para
                  navegar ou crie um novo evento.
                </p>
              </div>
            </div>
          ) : null}

          {recurring.length > 0 ? (
            <div className="card" style={{ marginTop: "var(--s4)" }}>
              <div className="panel-title">
                <Icon name="refresh" /> Eventos recorrentes
                <span className="count">· {recurring.length}</span>
              </div>
              {recurring.map((ev) => (
                <div className="list-row" key={ev.id} {...eventActivation(ev)}>
                  <div style={{ flex: 1 }}>
                    <div className="nm">{ev.titulo}</div>
                    <div className="sub">
                      {ev.hora ? `${ev.hora} · ` : ""}
                      {ev.recorrencia === "semanal" ? "Semanal" : "Recorrente"}
                    </div>
                  </div>
                  <span className="pill">Recorrente</span>
                </div>
              ))}
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

      {selected && !editing ? (
        <EventDetailModal
          event={selected}
          busy={mutBusy}
          error={mutError}
          onClose={() => {
            setSelected(null);
            setMutError(null);
          }}
          onEdit={() => {
            setFormError(null);
            setEditing(selected);
            setSelected(null);
          }}
          onDelete={() => void handleDelete()}
          onConfirm={() => void handleConfirm()}
        />
      ) : null}

      {showForm || editing ? (
        <EventFormModal
          event={editing ?? undefined}
          busy={saving}
          error={formError}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
            setFormError(null);
          }}
          onSubmit={(input) => void (editing ? handleEdit(input) : handleCreate(input))}
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
