"use client";

/**
 * Formulário de agendar multiplicação (POST /multiplicacoes) — form-field +
 * btn-primary. A célula é obrigatória; a data prevista é opcional — sem data, a
 * multiplicação nasce `sem_agendamento` e a aba correspondente destaca a
 * pendência. Falha ao salvar mantém o formulário com erro inline.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { CellSummary } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import { Icon } from "@/lib/icons";
import type { ScheduleMultiplicacaoInput } from "@/lib/multiplicacoes-api";

export interface ScheduleMultModalProps {
  cells: CellSummary[];
  leaders: Contact[];
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: ScheduleMultiplicacaoInput) => void;
}

export function ScheduleMultModal({
  cells,
  leaders,
  busy,
  error,
  onClose,
  onSubmit,
}: ScheduleMultModalProps) {
  const [celulaId, setCelulaId] = useState("");
  const [dataPrevista, setDataPrevista] = useState("");
  const [novoLiderId, setNovoLiderId] = useState("");
  const [descendencia, setDescendencia] = useState("");
  const [touched, setTouched] = useState(false);

  const celulaError = touched && !celulaId ? "Selecione a célula que vai multiplicar." : undefined;

  const submit = () => {
    setTouched(true);
    if (!celulaId) return;
    onSubmit({
      celulaId,
      dataPrevista: dataPrevista || null,
      novoLiderId: novoLiderId || null,
      descendencia: descendencia.trim() || null,
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Agendar multiplicação"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Agendar multiplicação</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

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

          <div className={`field${celulaError ? " invalid" : ""}`}>
            <label htmlFor="sm-celula">Célula que vai multiplicar</label>
            <select id="sm-celula" value={celulaId} onChange={(e) => setCelulaId(e.target.value)} autoFocus>
              <option value="">Selecione…</option>
              {cells.map((c) => (
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

          <Field
            label="Data prevista"
            type="date"
            value={dataPrevista}
            onChange={(e) => setDataPrevista(e.target.value)}
            helper="Opcional. Sem data, fica como pendência sem agendamento."
          />

          <div className="field">
            <label htmlFor="sm-lider">Novo líder</label>
            <select id="sm-lider" value={novoLiderId} onChange={(e) => setNovoLiderId(e.target.value)}>
              <option value="">A definir</option>
              {leaders.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nome}
                </option>
              ))}
            </select>
          </div>

          <Field
            label="Descendência"
            value={descendencia}
            onChange={(e) => setDescendencia(e.target.value)}
            placeholder="Ex.: Raniel Levi"
            helper="Opcional. Descendência G12 da nova célula."
          />

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Agendando…">
              Agendar
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
