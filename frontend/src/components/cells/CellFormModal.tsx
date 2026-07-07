"use client";

/**
 * Formulário de criar/editar célula (api-cells) — form-field + btn-primary.
 * cobertura_espiritual é OBRIGATÓRIA: o submit fica bloqueado enquanto o campo
 * estiver vazio (espelha a validação de borda do backend). Falha ao salvar
 * mantém o formulário preenchido com erro inline (ex.: 403 sem permissão).
 *
 * Cobertura espiritual ≠ líder disponível: é texto livre com SUGESTÕES
 * (datalist, coverageOptions = pastores; G12 pastoral formal fica para
 * modelagem futura) — quem já tem célula, ativa ou não, continua aparecendo
 * como cobertura. Dia/horário viajam separados (diaReuniao + horario HH:MM,
 * campos que o backend já possui).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { CellSummary, UpsertCellInput } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import { Icon } from "@/lib/icons";

const DIAS_SEMANA = [
  "Domingo",
  "Segunda-feira",
  "Terça-feira",
  "Quarta-feira",
  "Quinta-feira",
  "Sexta-feira",
  "Sábado",
] as const;

export interface CellFormModalProps {
  /** Célula em edição; ausente = criação. */
  cell?: CellSummary | null;
  /** Pessoas elegíveis como líder da célula (aptas, sem célula ativa). */
  leaders: Contact[];
  /** Sugestões para a cobertura espiritual (pastores; não exclui quem já tem célula). */
  coverageOptions: Contact[];
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: UpsertCellInput) => void;
}

export function CellFormModal({
  cell,
  leaders,
  coverageOptions,
  busy,
  error,
  onClose,
  onSubmit,
}: CellFormModalProps) {
  const editing = Boolean(cell);
  const [nome, setNome] = useState(cell?.nome ?? "");
  const [liderId, setLiderId] = useState(cell?.liderId ?? "");
  const [diaReuniao, setDiaReuniao] = useState(cell?.diaReuniao ?? "");
  const [horario, setHorario] = useState(cell?.horario ?? "");
  const [cobertura, setCobertura] = useState(cell?.coberturaEspiritual ?? "");
  const [ativo, setAtivo] = useState(cell?.ativo ?? true);
  const [touched, setTouched] = useState(false);

  // Valor legado de dia ("Quinta 20h") vira opção extra do select: editar sem
  // mexer no campo preserva a string antiga em vez de apagá-la.
  const legacyDia =
    diaReuniao && !(DIAS_SEMANA as readonly string[]).includes(diaReuniao)
      ? diaReuniao
      : null;

  const nomeError = touched && !nome.trim() ? "Informe o nome da célula." : undefined;
  const coberturaError =
    touched && !cobertura.trim() ? "A cobertura espiritual é obrigatória." : undefined;

  const submit = () => {
    setTouched(true);
    if (!nome.trim() || !cobertura.trim()) return;
    onSubmit({
      id: cell?.id ?? null,
      nome: nome.trim(),
      liderId: liderId || null,
      diaReuniao: diaReuniao || null,
      horario: horario || null,
      coberturaEspiritual: cobertura.trim(),
      ativo,
    });
  };

  const title = editing ? "Editar célula" : "Nova célula";

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{title}</strong>
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

          <Field
            label="Nome da célula"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Ex.: Boas Novas"
            error={nomeError}
            autoFocus
          />

          <Field
            label="Cobertura espiritual"
            value={cobertura}
            onChange={(e) => setCobertura(e.target.value)}
            placeholder="Quem cobre espiritualmente esta célula"
            helper="Obrigatória. Sugestões: pastores — ter célula não impede de cobrir."
            error={coberturaError}
            list="cf-cobertura-sugestoes"
          />
          <datalist id="cf-cobertura-sugestoes">
            {coverageOptions.map((p) => (
              <option key={p.id} value={p.nome} />
            ))}
          </datalist>

          <div className="row">
            <div className="field">
              <label htmlFor="cf-lider">Líder da célula</label>
              <select
                id="cf-lider"
                value={liderId}
                onChange={(e) => setLiderId(e.target.value)}
              >
                <option value="">Sem líder definido</option>
                {leaders.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nome}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="row">
            <div className="field">
              <label htmlFor="cf-dia">Dia de reunião</label>
              <select
                id="cf-dia"
                value={diaReuniao}
                onChange={(e) => setDiaReuniao(e.target.value)}
              >
                <option value="">Sem dia definido</option>
                {legacyDia ? <option value={legacyDia}>{legacyDia} (atual)</option> : null}
                {DIAS_SEMANA.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
            <Field
              label="Horário"
              type="time"
              value={horario}
              onChange={(e) => setHorario(e.target.value)}
            />
          </div>

          <label className="check-row">
            <input
              type="checkbox"
              checked={ativo}
              onChange={(e) => setAtivo(e.target.checked)}
            />
            <span>Célula ativa</span>
          </label>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Salvando…"
            >
              {editing ? "Salvar alterações" : "Criar célula"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
