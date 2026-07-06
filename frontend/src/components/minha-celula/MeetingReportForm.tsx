"use client";

/**
 * Relatório da reunião (líder) — em SEÇÕES/cartões, não wizard. Orquestra:
 *   presença real (US-07), visitantes (US-08), registros (US-09), oferta/observações
 *   (US-10) e o envio final (US-11). Carrega o relatório consolidado (getReport) e
 *   as expectativas de visitante (getVisitorExpectations) para a reunião escolhida.
 *   Enquanto o relatório não é enviado, tudo é editável; após 'enviado', bloqueia
 *   (locked) e some o botão de envio. Cada escrita chama reload() para refletir o
 *   estado do servidor.
 */
import { useCallback, useEffect, useState } from "react";

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

  return (
    <div className="mc-stack">
      <div className="report-head">
        <div className="report-date">{formatMeetingDate(report.data)}</div>
        {report.tema ? <div className="report-tema">{report.tema}</div> : null}
        {locked ? (
          <div className="report-locked">
            <Icon name="lock" />
            <span>Relatório enviado — bloqueado para edição.</span>
          </div>
        ) : null}
      </div>

      <AttendanceSection
        token={token}
        reuniaoId={reuniaoId}
        members={members}
        presencas={report.presencas}
        locked={locked}
        onToast={onToast}
        onChanged={reload}
      />

      <VisitorsSection
        token={token}
        reuniaoId={reuniaoId}
        expectations={expectations}
        visitors={report.visitantes}
        locked={locked}
        onToast={onToast}
        onChanged={reload}
      />

      <RecordsSection
        token={token}
        reuniaoId={reuniaoId}
        members={members}
        records={report.records}
        locked={locked}
        onToast={onToast}
        onChanged={reload}
      />

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
    </div>
  );
}
