"use client";

/**
 * US-01 — cartão da próxima reunião da minha célula. Mostra data (com dia da
 * semana), hora, local e tema; quando não há ocorrência futura (ou sem célula),
 * exibe o empty "Próxima reunião ainda não definida." e desabilita as ações.
 * As ações são Confirmar presença (US-02) e Indicar visitante (US-03).
 */
import { DsButton } from "@/components/ds/Button";
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
        <Icon name="calendar" /> Sua próxima reunião
      </div>

      {meeting ? (
        <div className="mc-meeting-body">
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
            <DsButton variant="secondary" onClick={onIndicateVisitor}>
              <Icon name="plus" />
              <span>Indicar visitante</span>
            </DsButton>
          </div>
        </div>
      ) : (
        <div className="empty-state mc-empty-state">
          <Icon name="calendar" />
          <p>
            <strong>Próxima reunião ainda não definida.</strong> Assim que a liderança planejar, ela
            aparece aqui.
          </p>
          <div className="meeting-actions" aria-hidden="true">
            <DsButton variant="secondary" disabled>
              <Icon name="user" />
              <span>Confirmar presença</span>
            </DsButton>
            <DsButton variant="secondary" disabled>
              <Icon name="plus" />
              <span>Indicar visitante</span>
            </DsButton>
          </div>
        </div>
      )}
    </section>
  );
}
