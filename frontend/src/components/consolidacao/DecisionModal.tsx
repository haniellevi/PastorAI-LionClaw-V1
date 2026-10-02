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

import { Dialog as DsDialog } from "@/components/ds/Dialog";
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

import "../contacts/people-ux-v2.css";

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
    if (busy || !canSubmit) return;
    onSubmit({
      pessoa: pessoaId,
      origem,
      vinculo,
      celulaId: vinculo === "celula" ? celulaId || null : null,
    });
  };

  return (
    // W5A: shell manual → DsDialog (Esc/trap/backdrop/retorno de foco do
    // primitive); fechar bloqueado enquanto salva, como nas waves anteriores.
    <DsDialog
      className="people-ux-dialog"
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Lançar decisão por Jesus"
      description="Escolha a pessoa, a origem e o vínculo para registrar a decisão e iniciar o acompanhamento."
    >
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
                disabled={busy}
                aria-describedby={pessoaError ? "dec-pessoa-error" : undefined}
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
                <div id="dec-pessoa-error" className="err" role="alert">
                  {pessoaError}
                </div>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="dec-origem">Origem da decisão</label>
              <select
                id="dec-origem"
                disabled={busy}
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

          <fieldset className="choice-field" disabled={busy}>
            <legend>Vínculo da pessoa</legend>
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
          </fieldset>

          {vinculo === "celula" && !celulaFlowBlocked ? (
            <div className={`field${celulaError ? " invalid" : ""}`} style={{ margin: "var(--s4) 0 0" }}>
              <label htmlFor="dec-celula">Célula que participa</label>
              <select
                id="dec-celula"
                disabled={busy}
                aria-describedby={celulaError ? "dec-celula-error" : undefined}
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
                <div id="dec-celula-error" className="err" role="alert">
                  {celulaError}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="flow-note">
            <Icon name={celulaFlowBlocked ? "alert" : "clock"} />
            <span>
              {celulaFlowBlocked ? (
                <>
                  Nenhuma célula ativa com líder disponível. O fluxo de célula fica
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
                  Ao lançar esta decisão, a consolidação começa com prazo de 24h
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
    </DsDialog>
  );
}
