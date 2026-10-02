"use client";

/**
 * Modal de vínculo de célula (api-link-cell). Reutilizado por #ganhar e #contatos.
 * Bloqueia células inativas ou sem líder no próprio seletor (regra do backend),
 * e exibe erro inline quando o vínculo falha (ex.: 409 célula inativa).
 */
import { useCallback } from "react";
import { PaginatedLookup } from "@/components/lookups/PaginatedLookup";
import { fetchCellLookupPage, type CellLookup } from "@/lib/lookup-api";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Icon } from "@/lib/icons";
import type { Cell } from "@/lib/dashboard-api";

import "./people-ux-v2.css";

export function LinkCellModal({
  cells,
  token,
  onSessionExpired,
  contactName,
  busy,
  error,
  onClose,
  onLink,
}: {
  cells: Cell[];
  token?: string | null;
  onSessionExpired?: () => void;
  contactName: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onLink: (celulaId: string) => void;
}) {
  const title = "Conectar à célula";
  const loadPage = useCallback((q: string, page: number, signal: AbortSignal) => fetchCellLookupPage(token!, {q,page,signal}), [token]);

  // Fechar bloqueado durante o vínculo (Esc/backdrop/botão do DsDialog); as
  // linhas do seletor já ficam desabilitadas com busy.
  return (
    <DsDialog
      className="people-ux-dialog"
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={title}
    >
      <div className="modal-sub">{contactName}</div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      {token ? <PaginatedLookup<CellLookup> loadPage={loadPage} selected={null} onSelect={cell => { if (cell?.ativo && cell.liderId && !busy) onLink(cell.id); }} label="Buscar célula" inputId="link-cell-search" getLabel={cell => cell.nome} getDescription={cell => !cell.ativo ? "Inativa" : !cell.liderId ? "Sem líder" : "Ativa · com líder"} isDisabled={cell => !cell.ativo || !cell.liderId} disabled={busy} onSessionExpired={onSessionExpired} /> : <div className="picker">
        {cells.length === 0 ? (
          <p className="sub">Nenhuma célula cadastrada.</p>
        ) : (
          cells.map((c) => {
            const blocked = !c.ativo || !c.liderId;
            const reason = !c.ativo ? "Inativa" : !c.liderId ? "Sem líder" : null;
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
      </div>}
    </DsDialog>
  );
}
