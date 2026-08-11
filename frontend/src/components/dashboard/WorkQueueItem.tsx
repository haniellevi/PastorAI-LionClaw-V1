/**
 * work-queue-item — item da fila pastoral (estados pending/resolving/resolved).
 * Renderiza por tipo (visitante/atendimento/relatorio/conectar_celula/fonovisita)
 * com ações diretas: assumir, atribuir, mensagem interna, conectar à célula e
 * (re)agendar fonovisita. As ações são delegadas ao painel via callbacks.
 *
 * Gate 7 (Diamante Lapidado): linha contínua (não card) com avatar circular do
 * tipo, prazo com ícone+texto (nunca só cor), ação PRINCIPAL do tipo como
 * botão primário e secundárias como botões textuais quietos. Nenhuma ação foi
 * removida nem mudou de callback/condição:
 *  - visitante/conectar_celula → principal: Conectar à célula quando a
 *                                capacidade explícita permite;
 *  - fonovisita               → principal: Fonovisita (mesma semântica — não
 *                                remove a pendência atual);
 *  - atendimento/relatorio    → principal: Assumir;
 *  - Assumir segue presente em todos os tipos; Mensagem só aparece quando a
 *    capacidade por item veio confirmada pelo servidor; Atribuir depende da
 *    capacidade explícita recebida do painel.
 */
import { DsButton } from "@/components/ds/Button";
import { Icon, type IconKey } from "@/lib/icons";
import type { WorkItem } from "@/lib/dashboard-api";

import { DeadlineBadge } from "./DeadlineBadge";

/** Ícone + classe de cor por tipo de item (avatar circular da linha). */
const TYPE_VISUAL: Record<string, { icon: IconKey; cls: "v" | "h" | "r" }> = {
  visitante: { icon: "user", cls: "v" },
  conectar_celula: { icon: "user", cls: "v" },
  atendimento: { icon: "chat", cls: "h" },
  relatorio: { icon: "document", cls: "r" },
  fonovisita: { icon: "phone", cls: "v" },
};

const DEFAULT_VISUAL = { icon: "alert" as IconKey, cls: "h" as const };

export interface WorkQueueItemProps {
  item: WorkItem;
  now: number;
  /** Nome do responsável atual, resolvido pela equipe (ou null). */
  responsibleName: string | null;
  /** Capacidade já resolvida pelo painel; o item não infere papéis. */
  canLinkCell: boolean;
  /** Capacidade de atribuir itens da fila, já resolvida pelo painel. */
  canAssignQueue: boolean;
  /** Desabilita ações enquanto uma requisição do item está em curso. */
  busy?: boolean;
  /** Marca a saída animada (resolved) antes da remoção da lista. */
  resolving?: boolean;
  /** Aviso de concorrência exibido sob o item ("já tratado por <usuário>"). */
  conflict?: string | null;
  onAssume: (item: WorkItem) => void;
  onAssign: (item: WorkItem) => void;
  onMessage: (item: WorkItem) => void;
  onLinkCell: (item: WorkItem) => void;
  onFonovisita: (item: WorkItem) => void;
}

export function WorkQueueItem({
  item,
  now,
  responsibleName,
  canLinkCell,
  canAssignQueue,
  busy = false,
  resolving = false,
  conflict = null,
  onAssume,
  onAssign,
  onMessage,
  onLinkCell,
  onFonovisita,
}: WorkQueueItemProps) {
  const visual = TYPE_VISUAL[item.tipo] ?? DEFAULT_VISUAL;
  const isLinkCellItem =
    item.tipo === "visitante" || item.tipo === "conectar_celula";
  const showLinkCellAction = canLinkCell && isLinkCellItem;
  const isFonovisita = item.tipo === "fonovisita";
  const deadlinePrefix = isFonovisita ? "fonovisita" : "prazo";
  const assumido = item.status === "assumido";
  // Ação principal do TIPO: Conectar à célula > Fonovisita > Assumir.
  const assumeIsPrimary = !showLinkCellAction && !isFonovisita;

  return (
    <div
      className={`dh-item${resolving ? " resolving" : ""}`}
      data-q={item.id}
      data-state={resolving ? "resolving" : "pending"}
    >
      <span className={`dh-avatar ${visual.cls}`} aria-hidden="true">
        <Icon name={visual.icon} />
      </span>

      <div className="dh-item-body">
        <strong className="dh-item-title">{item.titulo}</strong>
        {item.contexto ? <div className="dh-item-meta">{item.contexto}</div> : null}
        <div className="dh-item-line">
          {responsibleName ? (
            <span className="dh-item-resp">
              {assumido ? "Em atendimento por" : "Responsável"}: {responsibleName}
            </span>
          ) : null}
          <DeadlineBadge prazo={item.prazo} now={now} prefix={deadlinePrefix} />
        </div>
        {conflict ? (
          <div className="dh-item-conflict" role="alert">
            <Icon name="alert" />
            {conflict}
          </div>
        ) : null}
      </div>

      <div className="dh-item-actions">
        {showLinkCellAction ? (
          <DsButton disabled={busy} onClick={() => onLinkCell(item)}>
            <Icon name="link" />
            <span>Conectar à célula</span>
          </DsButton>
        ) : null}

        {isFonovisita ? (
          <DsButton disabled={busy} onClick={() => onFonovisita(item)}>
            <Icon name="phone" />
            <span>Fonovisita</span>
          </DsButton>
        ) : null}

        <DsButton
          variant={assumeIsPrimary ? "primary" : "tertiary"}
          disabled={busy || assumido}
          onClick={() => onAssume(item)}
        >
          {assumido ? "Assumido" : "Assumir"}
        </DsButton>

        {canAssignQueue ? (
          <DsButton variant="tertiary" disabled={busy} onClick={() => onAssign(item)}>
            Atribuir
          </DsButton>
        ) : null}

        {item.canMessage ? (
          <DsButton variant="tertiary" disabled={busy} onClick={() => onMessage(item)}>
            Mensagem
          </DsButton>
        ) : null}
      </div>
    </div>
  );
}
