"use client";

/**
 * Drill-down de uma igreja no console master (M1): assinatura, custo de IA e
 * contadores (cross-tenant). Busca GET /admin/igrejas/{id} ao abrir, com atalho
 * para editar status/plano.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  fetchIgrejaDetail,
  type AdminIgreja,
  type AdminIgrejaDetail,
} from "@/lib/admin-api";

const STATUS_LABEL: Record<string, string> = {
  ativa: "Ativa",
  suspensa: "Suspensa",
  aguardando_aprovacao: "Aguardando aprovação",
  inadimplente: "Inadimplente",
};
const PLANO_LABEL: Record<string, string> = {
  ate_100: "Até 100",
  "101_200": "101–200",
  acima_201: "201+",
};

const brl = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const num = (v: number) => v.toLocaleString("pt-BR");

const GRID: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "var(--s3)",
};

interface Props {
  igreja: AdminIgreja;
  token: string;
  onClose: () => void;
  onEdit: () => void;
  onExpired: () => void;
  onApprove?: () => void;
  approving?: boolean;
  actionError?: string | null;
}

export function IgrejaDetailModal({
  igreja,
  token,
  onClose,
  onEdit,
  onExpired,
  onApprove,
  approving,
  actionError,
}: Props) {
  const pending = igreja.status === "aguardando_aprovacao";
  const [detail, setDetail] = useState<AdminIgrejaDetail | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    fetchIgrejaDetail(token, igreja.id)
      .then((d) => {
        if (active) setDetail(d);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof AdminSessionExpiredError) {
          onExpired();
          return;
        }
        setError("Não foi possível carregar o detalhe da igreja.");
      });
    return () => {
      active = false;
    };
  }, [token, igreja.id, onExpired]);

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Detalhe de ${igreja.nome}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{igreja.nome}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <div className="modal-form">
          {actionError ? (
            <div className="error-banner" role="alert">
              <span>{actionError}</span>
            </div>
          ) : null}
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
            </div>
          ) : !detail ? (
            <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
              <span className="spinner" aria-hidden="true" />
              <div className="sub" style={{ marginTop: "var(--s2)" }}>
                Carregando dados da igreja…
              </div>
            </div>
          ) : (
            <>
              <div style={GRID}>
                <Stat label="Status" value={STATUS_LABEL[detail.status] ?? detail.status} />
                <Stat
                  label="Plano"
                  value={detail.plano ? PLANO_LABEL[detail.plano] ?? detail.plano : "—"}
                />
                <Stat
                  label="Mensalidade"
                  value={detail.mensalidade != null ? brl(detail.mensalidade) : "—"}
                />
                <Stat label="Membros (painel)" value={num(detail.membros)} />
                <Stat label="Pessoas" value={num(detail.pessoas)} />
                <Stat label="Células" value={num(detail.celulas)} />
                <Stat label="Custo de IA" value={brl(detail.custoIa)} />
                <Stat label="Tokens de IA" value={num(detail.tokensIa)} />
              </div>

              <div style={{ fontWeight: 600, margin: "var(--s4) 0 var(--s2)" }}>
                Assinatura
              </div>
              {detail.assinatura ? (
                <div style={GRID}>
                  <Stat label="Plano (cobrança)" value={detail.assinatura.plano ?? "—"} />
                  <Stat label="Situação" value={detail.assinatura.status ?? "—"} />
                  <Stat
                    label="Próxima cobrança"
                    value={detail.assinatura.proximaCobranca ?? "—"}
                  />
                  <Stat label="Setup pago" value={detail.assinatura.setupPago ? "Sim" : "Não"} />
                </div>
              ) : (
                <p className="sub" style={{ color: "var(--muted)" }}>
                  Sem registro de assinatura (o provisionamento manual ainda não cria a
                  linha de billing).
                </p>
              )}
            </>
          )}

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Fechar
            </button>
            <Button variant="ghost" size="sm" onClick={onEdit}>
              Editar status/plano
            </Button>
            {pending && onApprove ? (
              <Button
                variant="primary"
                size="sm"
                onClick={onApprove}
                loading={approving}
                loadingText="Aprovando…"
              >
                Aprovar igreja
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="sub" style={{ color: "var(--muted)" }}>
        {label}
      </div>
      <div style={{ fontWeight: 600 }}>{value}</div>
    </div>
  );
}
