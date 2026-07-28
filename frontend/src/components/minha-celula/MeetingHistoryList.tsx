"use client";

/**
 * US-05 — histórico das reuniões passadas do próprio membro. Projeção mínima:
 * data, tema, minha presença (E5) e os visitantes que EU indiquei. Mais recentes
 * primeiro (o backend já ordena). Empty: "Nenhuma reunião no histórico ainda.".
 */
import { Icon } from "@/lib/icons";
import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import type { HistoryItem } from "@/lib/cells-api";
import { formatMeetingDate } from "./format";

/** Rótulo + tom da pílula por estado de presença (E5). */
function presenceView(estado: string): { label: string; tone: PillTone } {
  switch (estado) {
    case "participou":
      return { label: "Participei", tone: "ok" };
    case "faltou":
      return { label: "Faltei", tone: "danger" };
    case "confirmou":
      return { label: "Confirmei", tone: "accent" };
    default:
      return { label: "Não confirmei", tone: "muted" };
  }
}

export function MeetingHistoryList({ items }: { items: HistoryItem[] }) {
  return (
    <section className="card" aria-label="Histórico de reuniões">
      <div className="panel-title">
        <Icon name="clock" /> Meu histórico
        {items.length ? <span className="count">· {items.length}</span> : null}
      </div>

      {items.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="clock" />
          <p>
            <strong>Nenhuma reunião no histórico ainda.</strong>
          </p>
        </div>
      ) : (
        <div>
          {items.map((it, idx) => {
            const presence = presenceView(it.minha_presenca);
            const visitors = it.meus_visitantes_indicados;
            return (
              <div className="hist-item" key={`${it.data}-${idx}`}>
                <div className="grow hist-main">
                  <div className="nm hist-date">
                    {formatMeetingDate(it.data)}
                  </div>
                  {it.tema ? <div className="sub">{it.tema}</div> : null}
                  {visitors.length ? (
                    <div className="hist-visitors">
                      Meus visitantes: {visitors.join(", ")}
                    </div>
                  ) : null}
                </div>
                <StatusPill tone={presence.tone}>{presence.label}</StatusPill>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
