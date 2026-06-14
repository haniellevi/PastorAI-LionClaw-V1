"use client";

/**
 * Modal de vínculo de célula (api-link-cell). Reutilizado por #ganhar e #contatos.
 * Bloqueia células inativas ou sem líder no próprio seletor (regra do backend),
 * e exibe erro inline quando o vínculo falha (ex.: 409 célula inativa).
 */
import { Icon } from "@/lib/icons";
import type { Cell } from "@/lib/dashboard-api";

export function LinkCellModal({
  cells,
  contactName,
  busy,
  error,
  onClose,
  onLink,
}: {
  cells: Cell[];
  contactName: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onLink: (celulaId: string) => void;
}) {
  const title = "Conectar à célula";

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{title}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="modal-sub">{contactName}</div>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="picker">
          {cells.length === 0 ? (
            <p className="sub">Nenhuma célula cadastrada.</p>
          ) : (
            cells.map((c) => {
              const blocked = !c.ativo || !c.liderId;
              const reason = !c.ativo
                ? "Inativa"
                : !c.liderId
                  ? "Sem líder"
                  : null;
              return (
                <button
                  type="button"
                  key={c.id}
                  className="picker-row"
                  disabled={blocked || busy}
                  aria-disabled={blocked || undefined}
                  title={blocked ? `Indisponível · ${reason}` : undefined}
                  onClick={() => !blocked && onLink(c.id)}
                >
                  <span className="nm">{c.nome}</span>
                  {blocked ? (
                    <span className="pill muted">{reason}</span>
                  ) : (
                    <span className="sub">Ativa · com líder</span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
