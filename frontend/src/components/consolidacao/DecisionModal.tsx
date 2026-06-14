"use client";

/**
 * decision-modal — modal de "Lançar decisão por Jesus" (US-37/40).
 * Usado por #consolidar e #consol-individual. Escolhe o vínculo da pessoa:
 *
 *  - célula (fluxo A): quem já participa de célula. Você lança e assume a
 *    consolidação. Exige uma célula com líder; SEM célula disponível o fluxo A
 *    fica BLOQUEADO e o modal sugere o fluxo visitante.
 *  - visitante (fluxo B): sem vínculo. A consolidação abre prazo de 24h
 *    (deadline-badge) para conectar a pessoa a uma célula.
 *
 * Estados: closed · celula-flow · visitante-flow. O submit envia para
 * api-launch-decision (launchDecision) via callback do painel.
 */
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import type { CellSummary } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import type { DecisionVinculo, LaunchDecisionInput } from "@/lib/consolidacao-api";
import { Icon } from "@/lib/icons";

const ORIGENS = [
  "Culto de domingo",
  "Célula",
  "Evento / cruzada",
  "Conversa no WhatsApp",
  "Visita / fonovisita",
] as const;

export interface DecisionModalProps {
  /** Pessoas elegíveis para lançar a decisão. */
  contacts: Contact[];
  /** Células disponíveis (apenas ativas com líder entram no fluxo A). */
  cells: CellSummary[];
  /** Pré-seleção da pessoa (ex.: abrir a partir de um item da fila). */
  defaultPessoaId?: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: LaunchDecisionInput) => void;
}

export function DecisionModal({
  contacts,
  cells,
  defaultPessoaId,
  busy,
  error,
  onClose,
  onSubmit,
}: DecisionModalProps) {
  const [pessoaId, setPessoaId] = useState(defaultPessoaId ?? "");
  const [origem, setOrigem] = useState<string>(ORIGENS[0]);
  const [vinculo, setVinculo] = useState<DecisionVinculo>("celula");
  const [celulaId, setCelulaId] = useState("");
  const [touched, setTouched] = useState(false);

  const availableCells = useMemo(
    () => cells.filter((c) => c.ativo && c.liderId),
    [cells],
  );
  const noCellAvailable = availableCells.length === 0;

  // Fluxo A bloqueado quando não há célula disponível para vincular.
  const celulaFlowBlocked = vinculo === "celula" && noCellAvailable;

  const pessoaError = touched && !pessoaId ? "Selecione a pessoa." : undefined;
  const celulaError =
    touched && vinculo === "celula" && !celulaFlowBlocked && !celulaId
      ? "Selecione a célula que a pessoa participa."
      : undefined;

  const canSubmit =
    Boolean(pessoaId) &&
    !celulaFlowBlocked &&
    (vinculo === "visitante" || Boolean(celulaId));

  const submit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      pessoa: pessoaId,
      origem,
      vinculo,
      celulaId: vinculo === "celula" ? celulaId || null : null,
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Lançar decisão por Jesus"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Lançar decisão por Jesus</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <p className="modal-sub">
          Registre quem decidiu por Jesus para iniciar a consolidação. Ninguém que
          aceitou Jesus fica sem acompanhamento.
        </p>

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {error ? (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="row">
            <div className={`field${pessoaError ? " invalid" : ""}`}>
              <label htmlFor="dec-pessoa">Pessoa</label>
              <select
                id="dec-pessoa"
                value={pessoaId}
                onChange={(e) => setPessoaId(e.target.value)}
                aria-invalid={pessoaError ? true : undefined}
              >
                <option value="">Selecione um contato…</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
              {pessoaError ? (
                <div className="err" role="alert">
                  {pessoaError}
                </div>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="dec-origem">Origem da decisão</label>
              <select
                id="dec-origem"
                value={origem}
                onChange={(e) => setOrigem(e.target.value)}
              >
                {ORIGENS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="field" style={{ marginBottom: 0 }}>
            <label>Vínculo da pessoa</label>
            <div className="choice">
              <label className={vinculo === "celula" ? "on" : undefined}>
                <input
                  type="radio"
                  name="dec-vinculo"
                  value="celula"
                  checked={vinculo === "celula"}
                  onChange={() => setVinculo("celula")}
                />
                <span className="ct">
                  <Icon name="consolidar" />
                  Já participa de célula
                </span>
                <span className="cs">
                  Você lança e assume a consolidação. O ministério de consolidação é
                  avisado.
                </span>
              </label>
              <label className={vinculo === "visitante" ? "on" : undefined}>
                <input
                  type="radio"
                  name="dec-vinculo"
                  value="visitante"
                  checked={vinculo === "visitante"}
                  onChange={() => setVinculo("visitante")}
                />
                <span className="ct">
                  <Icon name="user" />
                  Visitante sem vínculo
                </span>
                <span className="cs">
                  Consolidação lança e abre prazo de 24h para conectar a uma célula.
                </span>
              </label>
            </div>
          </div>

          {vinculo === "celula" && !celulaFlowBlocked ? (
            <div className={`field${celulaError ? " invalid" : ""}`} style={{ margin: "var(--s4) 0 0" }}>
              <label htmlFor="dec-celula">Célula que participa</label>
              <select
                id="dec-celula"
                value={celulaId}
                onChange={(e) => setCelulaId(e.target.value)}
                aria-invalid={celulaError ? true : undefined}
              >
                <option value="">Selecione a célula…</option>
                {availableCells.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
              {celulaError ? (
                <div className="err" role="alert">
                  {celulaError}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="flow-note">
            <Icon name={celulaFlowBlocked ? "alert" : "sparkles"} />
            <span>
              {celulaFlowBlocked ? (
                <>
                  Nenhuma célula ativa com líder disponível — o fluxo de célula fica
                  bloqueado. Use <strong>Visitante sem vínculo</strong>: a consolidação
                  abre prazo de 24h para conectar a pessoa assim que houver célula.
                </>
              ) : vinculo === "celula" ? (
                <>
                  Fluxo de célula: a consolidação é assumida por você, sem prazo de 24h.
                  O ministério de consolidação é notificado.
                </>
              ) : (
                <>
                  Fluxo visitante: ao lançar, abre-se um prazo de 24h (deadline-badge)
                  para conectar a pessoa a uma célula. Atrasos são escalados.
                </>
              )}
            </span>
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Lançando…"
              disabled={!canSubmit}
              aria-disabled={!canSubmit || undefined}
              title={
                celulaFlowBlocked
                  ? "Sem célula disponível: use o fluxo visitante."
                  : undefined
              }
            >
              <Icon name="check" />
              <span>Lançar decisão</span>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
