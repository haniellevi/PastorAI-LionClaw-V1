"use client";

/**
 * transfer-conversation-modal — escolhe outro membro (com acesso ao inbox) para
 * assumir o atendimento. A lista já vem filtrada/ordenada pelo InboxScreen.
 *
 * Gate 8: migração MECÂNICA para o DsDialog da fundação — mesmas opções,
 * callbacks, erro e busy; Esc, trap, backdrop e retorno de foco vêm do
 * primitive (fechar é bloqueado enquanto busy, como antes).
 */
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
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
    <DsDialog
      open
      onClose={() => {
        if (!busy) onCancel();
      }}
      title="Transferir conversa"
      description={`Escolha quem vai assumir o atendimento de ${displayName(conversation)}.`}
      footer={
        <DsButton variant="tertiary" onClick={onCancel} disabled={busy}>
          Cancelar
        </DsButton>
      }
    >
      {error ? <DsBanner kind="error">{error}</DsBanner> : null}

      {loading ? (
        <p className="ib-picker-empty">Carregando equipe…</p>
      ) : members.length === 0 ? (
        <div className="ib-picker-empty">
          <Icon name="team" />
          <p>Nenhum outro membro com acesso ao inbox para receber a conversa.</p>
        </div>
      ) : (
        <div className="ib-picker">
          {members.map((m) => (
            <button
              key={m.usuarioId}
              type="button"
              className="ib-picker-row"
              onClick={() => onConfirm(m.usuarioId)}
              disabled={busy}
            >
              <span className="ib-picker-nm">{m.nome}</span>
              <span className="ib-picker-sub">{rolesSummary(m.papeis)}</span>
            </button>
          ))}
        </div>
      )}
    </DsDialog>
  );
}
