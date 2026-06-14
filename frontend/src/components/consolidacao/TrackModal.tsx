"use client";

/**
 * track-modal — trilha de consolidação individual (api-pipeline / advance-stage).
 *
 * Renderiza os passos (TRACK_STEPS) com estado done/now derivado do registro da
 * pessoa + etapas confirmadas na sessão. A confirmação de etapa é restrita ao
 * consolidador responsável (gate de identidade); concluir é liberado apenas com
 * todas as etapas obrigatórias confirmadas. Quando a consolidação não é conhecida
 * nesta sessão (sem consolidacaoId), as ações ficam desabilitadas com a razão —
 * reflexo honesto de que o backend não expõe leitura de consolidação por pessoa.
 */
import { useMemo } from "react";

import { DeadlineBadge } from "@/components/dashboard/DeadlineBadge";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Button } from "@/components/ui/Button";
import {
  MANDATORY_ETAPAS,
  TRACK_STEPS,
  canConclude,
  countMandatory,
  derivedStages,
  etapaLabel,
  mergeStages,
  nextMandatory,
} from "@/lib/consolidacao-api";
import type { Contact } from "@/lib/contacts-api";
import type { SessionConsolidation } from "@/lib/consolidacao-store";
import { initials } from "@/lib/g12-api";
import { Icon } from "@/lib/icons";

export interface TrackModalProps {
  contact: Contact;
  /** Vínculo de sessão (consolidacaoId/responsável/etapas) — pode faltar. */
  session: SessionConsolidation | undefined;
  /** Id do usuário logado (gate de identidade do consolidador). */
  selfId: string;
  /** Nome do consolidador responsável, quando conhecido. */
  consolidadorName: string | null;
  /** Instante atual do painel (transição do deadline-badge sem reload). */
  now: number;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (etapa: string) => void;
  onConclude: () => void;
}

export function TrackModal({
  contact,
  session,
  selfId,
  consolidadorName,
  now,
  busy,
  error,
  onClose,
  onConfirm,
  onConclude,
}: TrackModalProps) {
  const stages = useMemo(
    () => mergeStages(derivedStages(contact), session?.confirmedStages),
    [contact, session?.confirmedStages],
  );

  const done = countMandatory(stages);
  const total = MANDATORY_ETAPAS.length;
  const next = nextMandatory(stages);
  const allDone = canConclude(stages);
  const concluida = session?.concluida ?? false;

  const consolidacaoId = session?.consolidacaoId ?? null;
  const responsavelId = session?.responsavelId ?? null;
  const isResponsavel = !responsavelId || responsavelId === selfId;

  const canAct = Boolean(consolidacaoId) && !concluida && isResponsavel;

  const firstPending = next; // próxima etapa obrigatória "now"

  const note = concluida
    ? "Consolidação concluída — a pessoa entra no critério para a Universidade da Vida."
    : !consolidacaoId
      ? "A confirmação de etapas exige uma consolidação lançada ou atribuída nesta sessão. Lance ou atribua a decisão desta pessoa para habilitar."
      : !isResponsavel
        ? "Apenas o consolidador responsável pode confirmar etapas (gate de identidade)."
        : allDone
          ? "Todas as etapas obrigatórias estão confirmadas — conclua a consolidação."
          : "Concluir é liberado apenas com todas as etapas obrigatórias confirmadas.";

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Trilha de consolidação"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Trilha de consolidação</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <p className="modal-sub">Processo individual — da decisão à conclusão</p>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="recip">
          <span className="avatar">{initials(contact.nome)}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="nm">{contact.nome}</div>
            <div className="sub" style={{ color: "var(--muted)" }}>
              {consolidadorName
                ? `Consolidador: ${consolidadorName}`
                : "Sem consolidador atribuído"}
              {session?.vinculo === "visitante" ? " · visitante" : ""}
            </div>
            {session?.vinculo === "visitante" && session.prazoConexao ? (
              <div style={{ marginTop: 4 }}>
                <DeadlineBadge prazo={session.prazoConexao} now={now} prefix="prazo 24h" />
              </div>
            ) : null}
          </div>
          <StatusPill tone={allDone ? "ok" : done > 0 ? "accent" : "muted"}>
            {done} / {total}
          </StatusPill>
        </div>

        <div className="track">
          {TRACK_STEPS.map((step) => {
            const isDone = stages.has(step.etapa);
            const isNow = !isDone && step.etapa === firstPending;
            const cls = `stop${isDone ? " done" : ""}${isNow ? " now" : ""}`;
            return (
              <div className={cls} key={step.etapa}>
                <span className="dot">
                  {isDone ? <Icon name="check" /> : null}
                </span>
                <div>
                  <div className="nm">
                    {step.label}
                    {step.optional ? <span className="seg-chip">opcional</span> : null}
                  </div>
                  <div className="sub" style={{ color: "var(--muted)" }}>
                    {step.desc}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <p className="lock-note" style={{ marginTop: "var(--s4)" }}>
          <Icon name="lock" />
          {note}
        </p>

        <div className="modal-foot">
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Fechar
          </button>
          {allDone ? (
            <Button
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Concluindo…"
              disabled={!canAct}
              aria-disabled={!canAct || undefined}
              onClick={onConclude}
            >
              <Icon name="check" />
              <span>Concluir consolidação</span>
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Confirmando…"
              disabled={!canAct || !next}
              aria-disabled={!canAct || !next || undefined}
              onClick={() => next && onConfirm(next)}
            >
              <Icon name="check" />
              <span>{next ? `Confirmar: ${etapaLabel(next)}` : "Etapas confirmadas"}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
