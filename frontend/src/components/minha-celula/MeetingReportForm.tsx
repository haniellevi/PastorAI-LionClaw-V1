"use client";

/**
 * Relatório da reunião (líder) — divulgação progressiva em quatro etapas. Orquestra:
 *   presença real (US-07), visitantes (US-08), registros (US-09), oferta/observações
 *   (US-10) e o envio final (US-11). Carrega o relatório consolidado (getReport) e
 *   as expectativas de visitante (getVisitorExpectations) para a reunião escolhida.
 *   Enquanto o relatório não é enviado, tudo é editável; após 'enviado', bloqueia
 *   (locked) e some o botão de envio. A navegação organiza o trabalho sem inventar
 *   validações novas; cada escrita chama reload() para refletir o estado do servidor.
 */
import { useCallback, useEffect, useId, useState, type ReactNode } from "react";

import { DsButton } from "@/components/ds/Button";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  getReport,
  getVisitorExpectations,
  type ReportOut,
  type VisitorExpectationItem,
} from "@/lib/cell-meetings-api";
import type { CellMember } from "@/lib/cells-api";
import { formatMeetingDate } from "./format";

import { AttendanceSection } from "./AttendanceSection";
import { VisitorsSection } from "./VisitorsSection";
import { RecordsSection } from "./RecordsSection";
import { OfferingSection } from "./OfferingSection";
import { SubmitReportButton } from "./SubmitReportButton";
import type { FlashToast } from "./types";

type ReportStepIndex = 0 | 1 | 2 | 3;

function ReportStep({
  step,
  title,
  description,
  summary,
  open,
  complete,
  onToggle,
  children,
}: {
  step: ReportStepIndex;
  title: string;
  description: string;
  summary: string;
  open: boolean;
  complete: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const uid = useId();
  const headingId = `${uid}-heading`;
  const panelId = `${uid}-panel`;

  return (
    <section className={`mc-report-step${open ? " is-open" : ""}${complete ? " is-complete" : ""}`}>
      <h3 className="mc-report-step-heading" id={headingId}>
        <button
          type="button"
          className="mc-report-step-trigger"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
        >
          <span className="mc-report-step-marker" aria-hidden="true">
            <span>{complete ? <Icon name="check" size={14} /> : step + 1}</span>
          </span>
          <span className="mc-report-step-copy">
            <strong>{title}</strong>
            <span>{description}</span>
          </span>
          <span className="mc-report-step-summary">{summary}</span>
          <Icon name="caret" className="mc-report-step-caret" />
        </button>
      </h3>
      <div
        id={panelId}
        role="region"
        aria-labelledby={headingId}
        className="mc-report-step-body"
        hidden={!open}
      >
        {children}
      </div>
    </section>
  );
}

function recordSummary(records: ReportOut["records"]): string {
  if (records.length === 0) return "Sem registros";
  const decisions = records.filter((record) => record.tipo === "decisao").length;
  const prayers = records.filter((record) => record.tipo === "oracao").length;
  const parts: string[] = [];
  if (decisions) parts.push(`${decisions} ${decisions === 1 ? "decisão" : "decisões"}`);
  if (prayers) parts.push(`${prayers} ${prayers === 1 ? "oração" : "orações"}`);
  const others = records.length - decisions - prayers;
  if (others) parts.push(`${others} ${others === 1 ? "observação" : "observações"}`);
  return parts.join(", ");
}

function closingSummary(report: ReportOut): string {
  const parts: string[] = [];
  if (report.oferta_valor != null) parts.push("Oferta registrada");
  if (report.observacoes?.trim()) parts.push("Observações salvas");
  return parts.length ? parts.join(" · ") : "A revisar";
}

export function MeetingReportForm({
  token,
  reuniaoId,
  members,
  onToast,
}: {
  token: string;
  reuniaoId: string;
  members: CellMember[];
  onToast: FlashToast;
}) {
  const [report, setReport] = useState<ReportOut | null>(null);
  const [expectations, setExpectations] = useState<VisitorExpectationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeStep, setActiveStep] = useState<ReportStepIndex>(0);

  const load = useCallback(
    async (mode: "initial" | "reload") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const [reportRes, expRes] = await Promise.all([
          getReport(token, reuniaoId),
          getVisitorExpectations(token, reuniaoId),
        ]);
        setReport(reportRes);
        setExpectations(expRes.expectations);
        setLoaded(true);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar o relatório.",
        );
      } finally {
        setLoading(false);
      }
    },
    [token, reuniaoId],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const reload = useCallback(() => void load("reload"), [load]);

  if (loading && !loaded) {
    return (
      <div className="mc-stack">
        {Array.from({ length: 3 }).map((_, i) => (
          <div className="card skeleton" key={i} style={{ padding: "var(--s5)" }}>
            <div className="sk-line sk-sm" />
            <div className="sk-line sk-lg" />
          </div>
        ))}
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="error-banner" role="alert">
        <Icon name="alert" />
        <span>{error}</span>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => void load("initial")}
          disabled={loading}
        >
          Tentar novamente
        </button>
      </div>
    );
  }

  if (!report) return null;

  const locked = report.relatorio_status === "enviado";
  const present = report.presencas.filter((presence) => presence.estado === "compareceu").length;
  const attendanceSaved = members.length > 0 && report.presencas.length >= members.length;
  const summaries = [
    members.length
      ? `${present} de ${members.length} presentes`
      : "Nenhum membro cadastrado",
    report.visitantes.length
      ? `${report.visitantes.length} ${report.visitantes.length === 1 ? "registrado" : "registrados"}`
      : "Sem visitantes registrados",
    recordSummary(report.records),
    closingSummary(report),
  ];
  const progress = ((activeStep + 1) / 4) * 100;

  return (
    <div className="mc-report">
      {!locked ? (
        <div className="mc-report-pending" role="status">
          <span className="mc-report-pending-icon" aria-hidden="true">
            <Icon name="alert" />
          </span>
          <span>
            <strong>Relatório em andamento</strong>
            <span>Continue de onde parou e envie quando estiver tudo conferido.</span>
          </span>
        </div>
      ) : null}

      <header className="mc-report-head">
        <div>
          <h2>{formatMeetingDate(report.data)}</h2>
          {report.tema ? <p>Tema: {report.tema}</p> : null}
        </div>
        <span className={`mc-report-status${locked ? " is-sent" : ""}`}>
          <span aria-hidden="true" />
          {locked ? "Enviado" : "Rascunho"}
        </span>
      </header>

      {locked ? (
        <div className="mc-report-locked" role="status">
          <Icon name="lock" />
          <span>Relatório enviado e bloqueado para edição.</span>
        </div>
      ) : null}

      <div className="mc-report-mobile-progress" aria-live="polite">
        <span>{locked ? "Relatório enviado" : `Etapa ${activeStep + 1} de 4`}</span>
        <strong>{summaries[activeStep]}</strong>
      </div>

      <div className="mc-report-layout">
        <div className="mc-report-flow">
          <ReportStep
            step={0}
            title="Presença"
            description="Confirme quem participou da reunião."
            summary={summaries[0]!}
            open={activeStep === 0}
            complete={locked || attendanceSaved}
            onToggle={() => setActiveStep(0)}
          >
            <AttendanceSection
              token={token}
              reuniaoId={reuniaoId}
              members={members}
              presencas={report.presencas}
              locked={locked}
              onToast={onToast}
              onChanged={reload}
            />
          </ReportStep>

          <ReportStep
            step={1}
            title="Visitantes"
            description="Confirme os esperados e registre quem chegou."
            summary={summaries[1]!}
            open={activeStep === 1}
            complete={locked}
            onToggle={() => setActiveStep(1)}
          >
            <VisitorsSection
              token={token}
              reuniaoId={reuniaoId}
              expectations={expectations}
              visitors={report.visitantes}
              locked={locked}
              onToast={onToast}
              onChanged={reload}
            />
          </ReportStep>

          <ReportStep
            step={2}
            title="Registros"
            description="Anote decisões, orações e acompanhamentos."
            summary={summaries[2]!}
            open={activeStep === 2}
            complete={locked}
            onToggle={() => setActiveStep(2)}
          >
            <RecordsSection
              token={token}
              reuniaoId={reuniaoId}
              members={members}
              records={report.records}
              locked={locked}
              onToast={onToast}
              onChanged={reload}
            />
          </ReportStep>

          <ReportStep
            step={3}
            title="Fechamento e envio"
            description="Revise oferta, observações e envie à Central."
            summary={summaries[3]!}
            open={activeStep === 3}
            complete={locked}
            onToggle={() => setActiveStep(3)}
          >
            <OfferingSection
              token={token}
              reuniaoId={reuniaoId}
              ofertaValor={report.oferta_valor}
              observacoes={report.observacoes}
              locked={locked}
              onToast={onToast}
              onSaved={reload}
            />

            {!locked ? (
              <SubmitReportButton
                token={token}
                reuniaoId={reuniaoId}
                onToast={onToast}
                onSubmitted={reload}
              />
            ) : null}
          </ReportStep>
        </div>

        <aside className="mc-report-summary" aria-labelledby="mc-report-summary-title">
          <h3 id="mc-report-summary-title">Resumo do relatório</h3>
          <div className="mc-report-summary-status">
            <span>Status</span>
            <strong>{locked ? "Enviado" : "Rascunho"}</strong>
          </div>
          <div className="mc-report-progress-copy">
            <span>Etapa atual</span>
            <strong>{activeStep + 1} de 4</strong>
          </div>
          <div
            className="mc-report-progress"
            role="progressbar"
            aria-label="Progresso entre as etapas do relatório"
            aria-valuemin={1}
            aria-valuemax={4}
            aria-valuenow={activeStep + 1}
          >
            <span style={{ transform: `scaleX(${progress / 100})` }} />
          </div>
          <ol className="mc-report-summary-list">
            {["Presença", "Visitantes", "Registros", "Fechamento"].map((label, index) => (
              <li key={label} className={index === activeStep ? "is-current" : undefined}>
                <span className="mc-report-summary-icon" aria-hidden="true">
                  <Icon name={index === 0 ? "team" : index === 1 ? "user" : index === 2 ? "document" : "send"} />
                </span>
                <span>
                  <strong>{label}</strong>
                  <small>{summaries[index]}</small>
                </span>
              </li>
            ))}
          </ol>
          {!locked ? (
            <DsButton variant="secondary" block onClick={() => setActiveStep(3)}>
              <Icon name="eye" />
              <span>Revisar fechamento</span>
            </DsButton>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
