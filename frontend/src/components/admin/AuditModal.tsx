"use client";

/**
 * Auditoria do console master (M3): lista as ações cross-tenant recentes — quem
 * provisionou/aprovou/editou/excluiu qual igreja ou plano. Lê GET /admin/audit
 * (tabela platform_audit_log, migration 0013). Somente leitura.
 */
import { useCallback, useEffect, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  fetchAudit,
  type AdminAuditEntry,
} from "@/lib/admin-api";

const ACAO_LABEL: Record<string, string> = {
  provisionar: "Provisionou igreja",
  aprovar: "Aprovou igreja",
  editar: "Editou igreja",
  excluir: "Excluiu igreja",
  plano_criar: "Criou plano",
  plano_editar: "Editou plano",
  plano_excluir: "Excluiu plano",
};

function quando(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resumoDetalhe(d: Record<string, unknown> | null): string {
  if (!d) return "";
  // de/para (edição de igreja): mostra a transição de status/plano.
  if (d.de && d.para) {
    const de = d.de as Record<string, unknown>;
    const para = d.para as Record<string, unknown>;
    const partes: string[] = [];
    for (const k of ["status", "plano"]) {
      if (de[k] !== para[k]) partes.push(`${k}: ${de[k] ?? "—"} → ${para[k] ?? "—"}`);
    }
    return partes.join(" · ");
  }
  return Object.entries(d)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v ?? "—"}`)
    .join(" · ");
}

export interface AuditModalProps {
  token: string;
  onClose: () => void;
  onExpired: () => void;
}

export function AuditModal({ token, onClose, onExpired }: AuditModalProps) {
  const [rows, setRows] = useState<AdminAuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    setError(null);
    try {
      setRows(await fetchAudit(token, 100));
    } catch (err) {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setError("Não foi possível carregar a auditoria.");
    } finally {
      if (refresh) setRefreshing(false);
    }
  }, [token, onExpired]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    // W5A: shell manual → DsDialog (Esc/trap/backdrop/retorno de foco do
    // primitive); somente leitura — fechar sempre disponível.
    <DsDialog
      open
      onClose={onClose}
      title="Auditoria"
      description="Últimas 100 ações administrativas, da mais recente para a mais antiga."
      className="admin-audit-dialog"
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Fechar
          </button>
          <Button
            variant="ghost"
            size="sm"
            loading={refreshing}
            loadingText="Atualizando…"
            onClick={() => void load(true)}
          >
            Atualizar
          </Button>
        </>
      }
    >
      <div className="admin-audit-content">
        {error ? (
          <div className="error-banner" role="alert">
            <span>{error}</span>
          </div>
        ) : null}

        {rows === null ? (
          <div className="admin-audit-loading" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <div className="sub">Carregando a auditoria…</div>
          </div>
        ) : rows.length === 0 ? (
          <p className="sub admin-audit-empty">Nenhuma ação registrada ainda.</p>
        ) : (
          <table className="data-table admin-audit-table">
            <colgroup>
              <col className="admin-audit-col-when" />
              <col className="admin-audit-col-action" />
              <col className="admin-audit-col-target" />
              <col className="admin-audit-col-actor" />
            </colgroup>
            <thead>
              <tr>
                <th>Quando</th>
                <th>Ação</th>
                <th>Alvo</th>
                <th>Por</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="num" data-label="Quando">
                    <span className="admin-audit-value">{quando(r.createdAt)}</span>
                  </td>
                  <td data-label="Ação">
                    <span className="admin-audit-value">{ACAO_LABEL[r.acao] ?? r.acao}</span>
                  </td>
                  <td data-label="Alvo">
                    <div className="admin-audit-value">
                      <strong className="nm">{r.alvoNome ?? "—"}</strong>
                      {resumoDetalhe(r.detalhe) ? (
                        <div className="sub">{resumoDetalhe(r.detalhe)}</div>
                      ) : null}
                    </div>
                  </td>
                  <td data-label="Por">
                    <span className="sub admin-audit-value">{r.actorEmail ?? "—"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </DsDialog>
  );
}
