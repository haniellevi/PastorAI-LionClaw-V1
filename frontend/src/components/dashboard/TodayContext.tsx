import type { DiscipleNotice } from "@/lib/cell-notices-api";
import type { NextMeetingBody } from "@/lib/cells-api";
import type { DashboardShortcutTarget } from "@/lib/dashboard-responsibilities";
import type { EventItem } from "@/lib/events-api";
import { Icon, type IconKey } from "@/lib/icons";
import type { MouseEvent as ReactMouseEvent } from "react";

const SHORTCUT_META: Record<
  DashboardShortcutTarget,
  { label: string; description: string; icon: IconKey }
> = {
  "central-celula": {
    label: "Central de Células",
    description: "Acompanhar células e exceções",
    icon: "central-celula",
  },
  "minha-celula": {
    label: "Minha Célula",
    description: "Reunião, avisos e comunidade",
    icon: "central-celula",
  },
  inbox: {
    label: "Conversas",
    description: "Atendimentos pelo WhatsApp oficial",
    icon: "chat",
  },
  ganhar: {
    label: "Ganhar",
    description: "Visitantes e próximos passos",
    icon: "ganhar",
  },
  consolidar: {
    label: "Consolidar",
    description: "Acompanhamentos em andamento",
    icon: "consolidar",
  },
  g12: {
    label: "Jornada G12",
    description: "Discipulado e desenvolvimento",
    icon: "g12",
  },
  enviar: {
    label: "Enviar",
    description: "Multiplicação e missão",
    icon: "enviar",
  },
  calendario: {
    label: "Agenda",
    description: "Próximos eventos da igreja",
    icon: "calendar",
  },
};

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function selectUpcomingEvents(
  events: readonly EventItem[],
  now = new Date(),
  limit = 3,
): EventItem[] {
  const today = localDateKey(now);
  return events
    .filter(
      (event) =>
        event.data != null &&
        event.data >= today,
    )
    .sort((a, b) => {
      const aKey = `${a.data ?? ""}T${a.hora ?? "23:59"}:${a.id}`;
      const bKey = `${b.data ?? ""}T${b.hora ?? "23:59"}:${b.id}`;
      return aKey.localeCompare(bKey);
    })
    .slice(0, limit);
}

function formatDateLabel(value: string, now: Date): string {
  const today = localDateKey(now);
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (value === today) return "Hoje";
  if (value === localDateKey(tomorrow)) return "Amanhã";

  return new Date(`${value}T12:00:00`).toLocaleDateString("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
}

function whenLabel(data: string, hora: string | null, now: Date): string {
  const date = formatDateLabel(data, now);
  return hora ? `${date}, ${hora}` : date;
}

function activateHashLink(
  event: ReactMouseEvent<HTMLAnchorElement>,
  target: string,
  onNavigate: (target: string) => void,
): void {
  // Preserve native link behavior for new-tab/window gestures and context menu.
  // Plain activation still goes through the shell navigator so its local route
  // state updates immediately and remains consistent with the rest of the app.
  if (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  event.preventDefault();
  onNavigate(target);
}

export function TodayContext({
  title,
  loading,
  events,
  meeting,
  notices,
  showEvents,
  showMeeting,
  shortcuts,
  onNavigate,
  now = new Date(),
}: {
  title: string;
  loading: boolean;
  events: readonly EventItem[];
  meeting: NextMeetingBody | null;
  notices: readonly DiscipleNotice[];
  showEvents: boolean;
  showMeeting: boolean;
  shortcuts: readonly DashboardShortcutTarget[];
  onNavigate: (target: string) => void;
  now?: Date;
}) {
  const upcoming = selectUpcomingEvents(events, now);
  const recentNotices = notices.slice(0, 2);

  return (
    <section className="dh-panel dh-context" aria-label={title} aria-busy={loading}>
      <h3 className="dh-panel-title">{title}</h3>

      {loading ? (
        <div className="dh-context-skeleton" aria-hidden="true">
          <div className="sk-line sk-md" />
          <div className="sk-line sk-sm" />
          <div className="sk-line sk-lg" />
        </div>
      ) : (
        <div className="dh-context-body">
          {showEvents ? (
            <section className="dh-context-section" aria-labelledby="dh-upcoming-title">
              <h4 id="dh-upcoming-title" className="dh-context-title">
                Próximos eventos
              </h4>
              {upcoming.length > 0 ? (
                <div className="dh-context-list">
                  {upcoming.map((event) => (
                    <a
                      href="#calendario"
                      className="dh-context-row is-link"
                      key={event.id}
                      onClick={(click) => activateHashLink(click, "calendario", onNavigate)}
                    >
                      <span className="dh-context-icon" aria-hidden="true">
                        <Icon name="calendar" />
                      </span>
                      <span className="dh-context-copy">
                        <span className="dh-context-name">{event.titulo}</span>
                        <time className="dh-context-meta" dateTime={`${event.data}T${event.hora ?? "00:00"}`}>
                          {whenLabel(event.data!, event.hora, now)}
                          {event.status === "a_confirmar"
                            ? " · Pendente de confirmação"
                            : ""}
                        </time>
                      </span>
                    </a>
                  ))}
                </div>
              ) : (
                <p className="dh-context-empty">Nenhum evento futuro publicado.</p>
              )}
            </section>
          ) : null}

          {showMeeting ? (
            <section className="dh-context-section" aria-labelledby="dh-meeting-title">
              <h4 id="dh-meeting-title" className="dh-context-title">
                Sua próxima reunião
              </h4>
              {meeting ? (
                <a
                  href="#minha-celula"
                  className="dh-context-row is-link"
                  onClick={(click) =>
                    activateHashLink(click, "minha-celula", onNavigate)
                  }
                >
                  <span className="dh-context-icon" aria-hidden="true">
                    <Icon name="central-celula" />
                  </span>
                  <span className="dh-context-copy">
                    <span className="dh-context-name">{meeting.tema ?? "Reunião da célula"}</span>
                    <time className="dh-context-meta" dateTime={`${meeting.data}T${meeting.hora ?? "00:00"}`}>
                      {whenLabel(meeting.data, meeting.hora, now)}
                      {meeting.local ? ` · ${meeting.local}` : ""}
                    </time>
                  </span>
                </a>
              ) : (
                <p className="dh-context-empty">Nenhuma próxima reunião planejada.</p>
              )}
            </section>
          ) : null}

          <section className="dh-context-section" aria-labelledby="dh-notices-title">
            <h4 id="dh-notices-title" className="dh-context-title">
              Avisos
            </h4>
            {recentNotices.length > 0 ? (
              <div className="dh-context-list">
                {recentNotices.map((notice) => (
                  <article className="dh-context-row" key={notice.id}>
                    <span className="dh-context-icon" aria-hidden="true">
                      <Icon name="bell" />
                    </span>
                    <span className="dh-context-copy">
                      <span className="dh-context-name">{notice.titulo}</span>
                      <span className="dh-context-meta">{notice.conteudo}</span>
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="dh-context-empty">Nenhum aviso novo.</p>
            )}
          </section>

          {shortcuts.length > 0 ? (
            <nav className="dh-context-section" aria-labelledby="dh-shortcuts-title">
              <h4 id="dh-shortcuts-title" className="dh-context-title">
                Seus espaços
              </h4>
              <div className="dh-shortcuts">
                {shortcuts.map((target) => {
                  const meta = SHORTCUT_META[target];
                  return (
                    <a
                      href={`#${target}`}
                      className="dh-shortcut"
                      key={target}
                      onClick={(click) => activateHashLink(click, target, onNavigate)}
                    >
                      <span className="dh-shortcut-icon" aria-hidden="true">
                        <Icon name={meta.icon} />
                      </span>
                      <span className="dh-context-copy">
                        <span className="dh-context-name">{meta.label}</span>
                        <span className="dh-context-meta">{meta.description}</span>
                      </span>
                    </a>
                  );
                })}
              </div>
            </nav>
          ) : null}
        </div>
      )}
    </section>
  );
}
