/**
 * work-queue-item — item da fila pastoral (estados pending/resolving/resolved).
 * Renderiza por tipo (visitante/atendimento/relatorio/conectar_celula/fonovisita)
 * com ações diretas: assumir, atribuir, mensagem interna, conectar à célula e
 * (re)agendar fonovisita. As ações são delegadas ao painel via callbacks.
 */
import { Icon, type IconKey } from "@/lib/icons";
import type { WorkItem } from "@/lib/dashboard-api";

import { DeadlineBadge } from "./DeadlineBadge";

/** Ícone + classe de cor por tipo de item (fiel ao artifact: .qicon.v/.h/.r). */
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
  const canLinkCell = item.tipo === "visitante" || item.tipo === "conectar_celula";
  const isFonovisita = item.tipo === "fonovisita";
  const deadlinePrefix = isFonovisita ? "fonovisita" : "prazo";
  const assumido = item.status === "assumido";

  return (
    <div
      className={`qitem${resolving ? " resolving" : ""}`}
      data-q={item.id}
      data-state={resolving ? "resolving" : "pending"}
    >
      <span className={`qicon ${visual.cls}`}>
        <Icon name={visual.icon} />
      </span>

      <div className="qbody">
        <strong>{item.titulo}</strong>
        {item.contexto ? <div className="meta">{item.contexto}</div> : null}
        <div className="meta-line">
          {responsibleName ? (
            <span className="resp">
              {assumido ? "Em atendimento por" : "Responsável"}: {responsibleName}
            </span>
          ) : null}
          <DeadlineBadge prazo={item.prazo} now={now} prefix={deadlinePrefix} />
        </div>
        {conflict ? (
          <div className="qconflict" role="alert">
            <Icon name="alert" />
            {conflict}
          </div>
        ) : null}
      </div>

      <div className="qactions">
        {canLinkCell ? (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={busy}
            onClick={() => onLinkCell(item)}
          >
            <Icon name="link" />
            <span>Conectar à célula</span>
          </button>
        ) : null}

        {isFonovisita ? (
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            onClick={() => onFonovisita(item)}
          >
            <Icon name="phone" />
            <span>Fonovisita</span>
          </button>
        ) : null}

        <button
          type="button"
          className={`btn btn-sm${!canLinkCell && !isFonovisita ? " btn-primary" : ""}`}
          disabled={busy || assumido}
          onClick={() => onAssume(item)}
        >
          {assumido ? "Assumido" : "Assumir"}
        </button>

        <button
          type="button"
          className="btn btn-sm"
          disabled={busy}
          onClick={() => onAssign(item)}
        >
          Atribuir
        </button>

        <button
          type="button"
          className="btn btn-sm"
          disabled={busy}
          onClick={() => onMessage(item)}
        >
          <Icon name="send" />
          <span>Mensagem</span>
        </button>
      </div>
    </div>
  );
}
