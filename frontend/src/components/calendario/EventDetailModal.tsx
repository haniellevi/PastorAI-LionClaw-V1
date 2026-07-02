"use client";

/**
 * Detalhe de um evento da agenda (EVT-4). Mostra título, quando (data/hora ou
 * recorrência), descrição, status/origem/recorrência e o estado de sync com o
 * Google, e oferece as ações Editar / Excluir / Confirmar.
 *
 *  - Ações só com `canManage` (pastor/admin — espelha o gate do backend); sem
 *    privilégio, evento 'a_confirmar' mostra aviso informativo (spec §5.3).
 *  - Editar: só para eventos com data fixa — recorrentes (data=null) não podem
 *    ser editados sem `dia_semana`, que o EventOut não expõe (EVT-1).
 *  - Excluir: confirmação em dois passos no próprio rodapé (sem prompt do browser).
 *  - Confirmar: só aparece quando status='a_confirmar' (POST /events/{id}/confirm).
 *
 * Reusa o sistema de modais corrigido (.modal-overlay/.modal) — rola dentro do
 * modal no mobile, sem overflow horizontal.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { formatLongDate, type EventItem } from "@/lib/events-api";
import { Icon, type IconKey } from "@/lib/icons";

/** status do evento -> rótulo + variante de .pill. */
const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  confirmado: { text: "Confirmado", cls: "ok" },
  a_confirmar: { text: "A confirmar", cls: "warn" },
  cancelado: { text: "Cancelado", cls: "danger" },
};

function DetailRow({ icon, label, value }: { icon: IconKey; label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: "10px", alignItems: "flex-start" }}>
      <span style={{ color: "var(--muted)", marginTop: "2px", flex: "none" }}>
        <Icon name={icon} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "12px", color: "var(--muted)" }}>{label}</div>
        <div
          style={{
            fontSize: "13.5px",
            color: "var(--fg)",
            fontWeight: 540,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

export function EventDetailModal({
  event,
  canManage,
  busy,
  error,
  onClose,
  onEdit,
  onDelete,
  onConfirm,
}: {
  event: EventItem;
  /** P0a: pastor/admin — libera Editar/Excluir/Confirmar (gate real no backend). */
  canManage: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onConfirm: () => void;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const status = event.status ? STATUS_LABEL[event.status] : undefined;
  const canEdit = canManage && event.data != null;
  const canConfirm = canManage && event.status === "a_confirmar";

  const when = event.data
    ? `${formatLongDate(event.data)}${event.hora ? ` · ${event.hora}` : ""}`
    : `Recorrente${event.recorrencia === "semanal" ? " · semanal" : ""}${
        event.hora ? ` · ${event.hora}` : ""
      }`;

  const showPills = Boolean(status || event.origem || event.recorrencia);

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Detalhe do evento ${event.titulo}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{event.titulo}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        {error ? (
          <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
          <DetailRow icon="calendar" label="Quando" value={when} />
          {event.descricao ? (
            <DetailRow icon="document" label="Descrição" value={event.descricao} />
          ) : null}

          {showPills ? (
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
              {status ? <span className={`pill ${status.cls}`}>{status.text}</span> : null}
              {event.origem ? (
                <span className="pill muted">
                  {event.origem === "google" ? "Importado do Google" : "Manual"}
                </span>
              ) : null}
              {event.recorrencia ? (
                <span className="pill accent">
                  {event.recorrencia === "semanal" ? "Semanal" : "Recorrente"}
                </span>
              ) : null}
            </div>
          ) : null}

          <DetailRow
            icon="link"
            label="Google Calendar"
            value={event.sincronizado ? "Sincronizado" : "Evento local — não enviado ao Google"}
          />

          {!canManage && event.status === "a_confirmar" ? (
            <p className="sub" style={{ margin: 0 }}>
              Este evento ainda será confirmado pela liderança. Você será avisado
              quando estiver definido.
            </p>
          ) : null}
        </div>

        {canManage ? (
          <div className="modal-foot" style={{ flexWrap: "wrap" }}>
            {canConfirm ? (
              <Button
                variant="primary"
                size="sm"
                onClick={onConfirm}
                loading={busy}
                loadingText="Confirmando…"
              >
                <Icon name="check" /> Confirmar
              </Button>
            ) : null}

            {canEdit ? (
              <button type="button" className="btn btn-sm" onClick={onEdit} disabled={busy}>
                Editar
              </button>
            ) : null}

            {confirmingDelete ? (
              <Button
                variant="danger"
                size="sm"
                onClick={onDelete}
                loading={busy}
                loadingText="Excluindo…"
              >
                Confirmar exclusão
              </Button>
            ) : (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => setConfirmingDelete(true)}
                disabled={busy}
              >
                <Icon name="trash" /> Excluir
              </button>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
