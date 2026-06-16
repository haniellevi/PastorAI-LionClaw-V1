"use client";

/**
 * delete-conversation-dialog — confirmação de exclusão (hard delete, admin).
 * Ação destrutiva e irreversível: deixa claro que apaga mensagens + mídia.
 */
import { Button } from "@/components/ui/Button";
import type { Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import { displayName } from "./conversation-format";

export function DeleteConversationDialog({
  conversation,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  conversation: Conversation;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onCancel} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Excluir conversa"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Excluir conversa</strong>
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
          Excluir a conversa com <strong>{displayName(conversation)}</strong>? Isso apaga
          permanentemente todas as mensagens e mídias desta conversa. Esta ação não pode
          ser desfeita.
        </p>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="modal-foot">
          <button type="button" className="btn btn-sm" onClick={onCancel} disabled={busy}>
            Cancelar
          </button>
          <Button
            variant="danger"
            size="sm"
            loading={busy}
            loadingText="Excluindo…"
            onClick={onConfirm}
          >
            <Icon name="trash" />
            <span>Excluir conversa</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
