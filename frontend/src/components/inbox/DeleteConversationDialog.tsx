"use client";

/**
 * delete-conversation-dialog — confirmação de exclusão (hard delete, admin).
 * Ação destrutiva e irreversível: deixa claro que apaga apenas a conversa,
 * suas mensagens e mídias — e que a Pessoa/Contato e seus vínculos ministeriais
 * (célula, liderança, cadastro, histórico) são PRESERVADOS. O ícone de lixeira
 * não exclui o contato; ao escrever de novo, uma nova conversa reusa a mesma
 * Pessoa (backend: DELETE /conversations/{id} não toca em Pessoa).
 *
 * Gate 8: migração MECÂNICA para o DsDialog — mesma confirmação, callbacks,
 * erro e busy; Esc/trap/backdrop/foco do primitive (fechar bloqueado em busy).
 * Destrutivo permanece coral (DsButton danger), nunca azul.
 */
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
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
    <DsDialog
      open
      onClose={() => {
        if (!busy) onCancel();
      }}
      title="Excluir conversa"
      footer={
        <>
          <DsButton variant="tertiary" onClick={onCancel} disabled={busy}>
            Cancelar
          </DsButton>
          <DsButton variant="danger" loading={busy} onClick={onConfirm}>
            <Icon name="trash" />
            <span>{busy ? "Excluindo…" : "Excluir conversa"}</span>
          </DsButton>
        </>
      }
    >
      <p className="ib-dialog-text">
        Excluir a conversa com <strong>{displayName(conversation)}</strong>? Apaga
        permanentemente as mensagens e as mídias <strong>desta conversa</strong>. Esta
        ação não pode ser desfeita.
      </p>

      <div className="preserve-note" role="note">
        <Icon name="shield" />
        <span>
          O contato <strong>não é excluído</strong>. O cadastro (nome e tipo) e os
          vínculos ministeriais — célula, liderança, consolidação e histórico — são
          preservados. Se a pessoa escrever de novo, uma nova conversa é aberta com o
          mesmo cadastro.
        </span>
      </div>

      {error ? <DsBanner kind="error">{error}</DsBanner> : null}
    </DsDialog>
  );
}
