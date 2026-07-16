"use client";

/**
 * Detalhe de um relatório de célula (api-reports). Modal somente-leitura aberto
 * pela ação "Ver" em #relatorios e #central-celula. Relatórios pendentes não
 * têm dados de reunião (id=null) — mostramos o estado pendente com a célula e a
 * semana, sem inventar números.
 */
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Icon } from "@/lib/icons";
import type { ReportItem } from "@/lib/reports-api";

function fmtOferta(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function ReportDetailModal({
  report,
  onClose,
}: {
  report: ReportItem;
  onClose: () => void;
}) {
  const recebido = report.status !== "pendente";

  // Somente-leitura: fechar sem restrição (Esc/backdrop/botão do DsDialog).
  return (
    <DsDialog open onClose={onClose} title={`Relatório — ${report.celulaNome ?? "Célula"}`}>
      <div className="modal-form">
        <div className="detail-head">
          <div>
            <h3>{report.celulaNome ?? "Célula"}</h3>
            <div className="sub mono">Semana {report.semana}</div>
          </div>
          <StatusPill tone={recebido ? "ok" : "warn"}>
            {recebido ? "Recebido" : "Pendente"}
          </StatusPill>
        </div>

        {recebido ? (
          <dl className="detail-list">
            <div>
              <dt>Presentes</dt>
              <dd className="num">{report.presentes ?? "—"}</dd>
            </div>
            <div>
              <dt>Visitantes</dt>
              <dd className="num">{report.visitantes ?? "—"}</dd>
            </div>
            <div>
              <dt>Decisões</dt>
              <dd className="num">{report.decisoes ?? "—"}</dd>
            </div>
            <div>
              <dt>Oferta</dt>
              <dd className="num">{fmtOferta(report.oferta)}</dd>
            </div>
            <div>
              <dt>Data da reunião</dt>
              <dd>{report.dataReuniao ?? "—"}</dd>
            </div>
            <div>
              <dt>Origem</dt>
              <dd>{report.origem ?? "WhatsApp"}</dd>
            </div>
          </dl>
        ) : (
          <div className="empty-state" style={{ padding: "var(--s5)" }}>
            <Icon name="clock" />
            <p>
              <strong>Relatório ainda não recebido.</strong> O líder envia o
              relatório semanal pelo WhatsApp oficial.
            </p>
          </div>
        )}

        {report.observacoes ? (
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Observações</label>
            <p className="sub" style={{ color: "var(--muted)" }}>{report.observacoes}</p>
          </div>
        ) : null}
      </div>
    </DsDialog>
  );
}
