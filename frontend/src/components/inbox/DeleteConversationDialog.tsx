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
import type { Conversation, PrivateDeletionReceipt } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import { displayName } from "./conversation-format";

export function DeleteConversationDialog({
  conversation,
  busy,
  error,
  onCancel,
  onConfirm,
  receipt,
  onRefresh,
}: {
  conversation: Conversation;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
  receipt?: PrivateDeletionReceipt | null;
  onRefresh?: () => void;
}) {
  return (
    <DsDialog
      open
      className="ib-dialog"
      onClose={() => {
        if (!busy) onCancel();
      }}
      title="Excluir conversa"
      footer={
        <>
          <DsButton variant="tertiary" onClick={onCancel} disabled={busy}>
            {receipt ? "Fechar" : "Cancelar"}
          </DsButton>
          {receipt ? (
            <DsButton variant="secondary" loading={busy} onClick={onRefresh}>Atualizar recibo</DsButton>
          ) : <DsButton variant="danger" loading={busy} onClick={onConfirm}>
            <Icon name="trash" />
            <span>{busy ? "Excluindo…" : "Excluir conversa"}</span>
          </DsButton>}
        </>
      }
    >
      {receipt ? <section aria-label="Recibo da exclusão privada">
        <div role="status">
          <strong>{receipt.estado === "concluido" ? "Exclusão concluída" : receipt.estado === "pendente_envio" ? "Exclusão pendente: envio em andamento" : "Exclusão pendente: limpeza de mídia"}</strong>
          <p>Recibo: {receipt.id}</p>
        </div>
        <p>O histórico foi removido do inbox. A limpeza externa pode continuar pendente. Este recibo não cobre backups nem cópias do provedor.</p>
        <ul>{Object.entries(receipt.camadas).map(([layer, counts]) => (
          <li key={layer}>{layer}: {counts.apagadas} apagadas; {counts.pendentes} pendentes; {counts.falhas} falhas.</li>
        ))}</ul>
      </section> : <p className="ib-dialog-text">
        Excluir a conversa com <strong>{displayName(conversation)}</strong>? Apaga
        as mensagens e solicita a limpeza privada das mídias <strong>desta conversa</strong>. Esta
        ação não pode ser desfeita.
      </p>}

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
