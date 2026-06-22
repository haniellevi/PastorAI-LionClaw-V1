"use client";

/**
 * Auditoria do console master (M3): lista as ações cross-tenant recentes — quem
 * provisionou/aprovou/editou/excluiu qual igreja ou plano. Lê GET /admin/audit
 * (tabela platform_audit_log, migration 0013). Somente leitura.
 */
import { useCallback, useEffect, useState } from "react";

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

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await fetchAudit(token, 100));
    } catch (err) {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setError("Não foi possível carregar a auditoria.");
    }
  }, [token, onExpired]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Auditoria do console"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 720 }}
      >
        <div className="modal-head">
          <strong>Auditoria</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <div className="modal-form">
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
            </div>
          ) : null}

          {rows === null ? (
            <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
              <span className="spinner" aria-hidden="true" />
              <div className="sub" style={{ marginTop: "var(--s2)" }}>
                Carregando a auditoria…
              </div>
            </div>
          ) : rows.length === 0 ? (
            <p className="sub" style={{ color: "var(--muted)" }}>
              Nenhuma ação registrada ainda.
            </p>
          ) : (
            <table className="data-table">
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
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {quando(r.createdAt)}
                    </td>
                    <td>{ACAO_LABEL[r.acao] ?? r.acao}</td>
                    <td className="nm">
                      {r.alvoNome ?? "—"}
                      {resumoDetalhe(r.detalhe) ? (
                        <div className="sub" style={{ color: "var(--muted)" }}>
                          {resumoDetalhe(r.detalhe)}
                        </div>
                      ) : null}
                    </td>
                    <td className="sub" style={{ color: "var(--muted)" }}>
                      {r.actorEmail ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Fechar
            </button>
            <Button variant="ghost" size="sm" onClick={() => void load()}>
              Atualizar
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
