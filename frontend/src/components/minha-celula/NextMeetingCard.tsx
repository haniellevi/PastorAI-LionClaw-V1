"use client";

/**
 * US-01 — cartão da próxima reunião da minha célula. Mostra data (com dia da
 * semana), hora, local e tema; quando não há ocorrência futura (ou sem célula),
 * exibe o empty "Próxima reunião ainda não definida." e desabilita as ações.
 * As ações são Confirmar presença (US-02) e Indicar visitante (US-03).
 */
import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import type { NextMeetingBody } from "@/lib/cells-api";
import { ConfirmAttendanceButton } from "./ConfirmAttendanceButton";
import { formatMeetingDate } from "./format";
import type { FlashToast } from "./types";

export function NextMeetingCard({
  token,
  meeting,
  onToast,
  onIndicateVisitor,
}: {
  token: string;
  meeting: NextMeetingBody | null;
  onToast: FlashToast;
  onIndicateVisitor: () => void;
}) {
  return (
    <section className="card" aria-label="Próxima reunião">
      <div className="panel-title">
        <Icon name="calendar" /> Próxima reunião
      </div>

      {meeting ? (
        <div style={{ padding: "var(--s4)" }}>
          <div className="meeting-date">{formatMeetingDate(meeting.data)}</div>
          <div className="meeting-meta">
            <span className="meeting-meta-item">
              <Icon name="clock" size={16} />
              {meeting.hora ?? "Horário a definir"}
            </span>
            {meeting.local ? (
              <span className="meeting-meta-item">
                <Icon name="link" size={16} />
                {meeting.local}
              </span>
            ) : null}
          </div>
          {meeting.tema ? (
            <p className="meeting-tema">
              <strong>Tema:</strong> {meeting.tema}
            </p>
          ) : null}

          <div className="meeting-actions">
            <ConfirmAttendanceButton
              token={token}
              reuniaoId={meeting.id}
              initialConfirmed={meeting.minha_presenca === "confirmou"}
              onToast={onToast}
            />
            <Button variant="default" onClick={onIndicateVisitor}>
              <Icon name="plus" />
              <span>Indicar visitante</span>
            </Button>
          </div>
        </div>
      ) : (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="calendar" />
          <p>
            <strong>Próxima reunião ainda não definida.</strong> Assim que a
            liderança planejar, ela aparece aqui.
          </p>
          <div className="meeting-actions" aria-hidden="true">
            <Button variant="default" disabled>
              <Icon name="user" />
              <span>Confirmar presença</span>
            </Button>
            <Button variant="default" disabled>
              <Icon name="plus" />
              <span>Indicar visitante</span>
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
