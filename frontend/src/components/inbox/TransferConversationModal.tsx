"use client";

/**
 * transfer-conversation-modal — escolhe outro membro (com acesso ao inbox) para
 * assumir o atendimento. A lista já vem filtrada/ordenada pelo InboxScreen.
 */
import type { Conversation } from "@/lib/conversations-api";
import type { TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

import { displayName } from "./conversation-format";

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrador",
  pastor: "Pastor",
  lider_g12: "Líder G12",
  operador: "Operador",
};

function rolesSummary(papeis: string[]): string {
  const labels = papeis
    .filter((p) => p in ROLE_LABEL)
    .map((p) => ROLE_LABEL[p]);
  return labels.length ? labels.join(" · ") : "Equipe";
}

export function TransferConversationModal({
  conversation,
  members,
  loading,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  conversation: Conversation;
  members: TeamMember[];
  loading: boolean;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (userId: string) => void;
}) {
  return (
    <div className="modal-overlay" onClick={onCancel} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Transferir conversa"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Transferir conversa</strong>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Fechar
          </button>
        </div>

        <p className="modal-sub">
          Escolha quem vai assumir o atendimento de{" "}
          <strong>{displayName(conversation)}</strong>.
        </p>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        {loading ? (
          <p className="panel-loading">Carregando equipe…</p>
        ) : members.length === 0 ? (
          <div className="empty-state" style={{ padding: "var(--s5)" }}>
            <Icon name="team" />
            <p className="sub">
              Nenhum outro membro com acesso ao inbox para receber a conversa.
            </p>
          </div>
        ) : (
          <div className="picker">
            {members.map((m) => (
              <button
                key={m.usuarioId}
                type="button"
                className="picker-row"
                onClick={() => onConfirm(m.usuarioId)}
                disabled={busy}
              >
                <span className="nm">{m.nome}</span>
                <span className="sub">{rolesSummary(m.papeis)}</span>
              </button>
            ))}
          </div>
        )}

        <div className="modal-foot">
          <button type="button" className="btn btn-sm" onClick={onCancel} disabled={busy}>
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}
