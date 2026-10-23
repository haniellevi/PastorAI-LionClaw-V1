"use client";

import "../cells/operations-ux-v2.css";

/**
 * Form de evento da agenda (api-events) — form-field + btn-primary. Cria um novo
 * evento ou, quando recebe `event` (EVT-4), edita um existente (PUT parcial). O
 * backend tenta espelhar no Google Calendar na criação; se o sync falhar, o
 * evento é salvo local e devolvido como não sincronizado (a tela sinaliza para
 * re-tentar). A edição não re-sincroniza (escopo EVT-6+).
 *
 * Wave Visual W3: migração mecânica para o DsDialog (Esc/trap/backdrop/retorno
 * de foco do primitive; fechar bloqueado em busy) — mesmos campos, callbacks e
 * textos de antes.
 */
import { useId, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import {
  PUBLICO_ALVO_LABEL,
  PUBLICOS_ALVO,
  REMINDER_WINDOW_OPTIONS,
  TIPO_LABEL,
  type CreateEventInput,
  type EventItem,
  type EventTipo,
  type PublicoAlvo,
  type ReminderWindowHours,
} from "@/lib/events-api";

function isReminderWindow(value: number | null | undefined): value is ReminderWindowHours {
  return REMINDER_WINDOW_OPTIONS.some((option) => option.value === value);
}

export function EventFormModal({
  event,
  defaultDate,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  /** Quando presente, o form abre em modo edição pré-preenchido (EVT-4). */
  event?: EventItem;
  defaultDate?: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: CreateEventInput) => void;
}) {
  const isEdit = event != null;
  const id = useId().replace(/:/g, "");
  const [titulo, setTitulo] = useState(event?.titulo ?? "");
  const [data, setData] = useState(event?.data ?? defaultDate ?? "");
  const [hora, setHora] = useState(event?.hora ?? "");
  const [descricao, setDescricao] = useState(event?.descricao ?? "");
  // P0b-3: categoria. "" = sem categoria (envia tipo:null); edição carrega o atual.
  const [tipo, setTipo] = useState<EventTipo | "">(event?.tipo ?? "");
  const [antecedenciaHoras, setAntecedenciaHoras] = useState<ReminderWindowHours | 0 | "custom" | "">(
    event?.antecedenciaHoras === 0
      ? 0
      : isReminderWindow(event?.antecedenciaHoras)
        ? event.antecedenciaHoras
        : event?.notificarEm
          ? "custom"
          : "",
  );
  const [publicos, setPublicos] = useState<Set<PublicoAlvo>>(
    () => new Set(
      (event?.publicoAlvo ?? []).filter(
        (publico): publico is PublicoAlvo => PUBLICOS_ALVO.includes(publico as PublicoAlvo),
      ),
    ),
  );
  const [publicosTouched, setPublicosTouched] = useState(false);
  const [windowTouched, setWindowTouched] = useState(false);
  const [touched, setTouched] = useState(false);

  const tituloError = touched && !titulo.trim() ? "Informe o título." : undefined;
  const dataError = touched && !data ? "Escolha a data." : undefined;
  const needsReminderPublic =
    typeof antecedenciaHoras === "number" && antecedenciaHoras > 0;
  const publicoError = touched && needsReminderPublic && publicos.size === 0;

  const togglePublico = (publico: PublicoAlvo) => {
    setPublicosTouched(true);
    setPublicos((previous) => {
      const next = new Set(previous);
      if (next.has(publico)) next.delete(publico);
      else next.add(publico);
      return next;
    });
  };

  const submit = () => {
    setTouched(true);
    if (!titulo.trim() || !data || (needsReminderPublic && publicos.size === 0)) return;
    const input: CreateEventInput = {
      titulo: titulo.trim(),
      data,
      hora: hora || null,
      descricao: descricao.trim() || null,
      tipo: tipo || null, // P0b-3: "" → null; literal → categoria
    };
    if (!isEdit || publicosTouched) input.publicoAlvo = [...publicos];
    if (!isEdit || windowTouched) {
      input.antecedenciaHoras =
        typeof antecedenciaHoras === "number" && isReminderWindow(antecedenciaHoras)
          ? antecedenciaHoras
          : null;
    }
    onSubmit(input);
  };

  const title = isEdit ? "Editar evento" : "Novo evento";

  return (
    <DsDialog className="ops-dialog"
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={title}
    >
      <form
        className="modal-form ops-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {error ? (
          <div className="error-banner" role="alert">
            <span>{error}</span>
          </div>
        ) : null}

        <Field
          label="Título"
          value={titulo}
          onChange={(e) => setTitulo(e.target.value)}
          placeholder="Ex.: Culto de domingo"
          error={tituloError}
          data-autofocus=""
        />

        <div className="row">
          <Field
            label="Data"
            type="date"
            value={data}
            onChange={(e) => setData(e.target.value)}
            error={dataError}
          />
          <Field
            label="Hora"
            type="time"
            value={hora}
            onChange={(e) => setHora(e.target.value)}
            helper="Opcional"
          />
        </div>

        <div className="field">
          <label htmlFor="ev-tipo">Categoria</label>
          <select
            id="ev-tipo"
            value={tipo}
            onChange={(e) => setTipo(e.target.value as EventTipo | "")}
          >
            <option value="">Sem categoria</option>
            {(Object.keys(TIPO_LABEL) as EventTipo[]).map((t) => (
              <option key={t} value={t}>
                {TIPO_LABEL[t]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor={`${id}-reminder-window`}>Janela do lembrete</label>
          <select
            id={`${id}-reminder-window`}
            value={antecedenciaHoras}
            aria-describedby={`${id}-reminder-window-help`}
            onChange={(e) => {
              setWindowTouched(true);
              const value = e.target.value;
              if (!value) {
                setAntecedenciaHoras("");
              } else if (value === "0") {
                setAntecedenciaHoras(0);
              } else if (value === "custom") {
                setAntecedenciaHoras("custom");
              } else {
                const hours = Number(value);
                setAntecedenciaHoras(
                  isReminderWindow(hours) ? hours : "",
                );
              }
            }}
          >
            <option value="">
              {antecedenciaHoras === "custom"
                ? "Remover horário específico"
                : "Sem lembrete"}
            </option>
            {antecedenciaHoras === "custom" ? (
              <option value="custom" disabled>
                Horário específico configurado
              </option>
            ) : null}
            {event?.antecedenciaHoras === 0 ? (
              <option value="0" disabled>
                Configuração existente: no dia do evento
              </option>
            ) : null}
            {REMINDER_WINDOW_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="helper" id={`${id}-reminder-window-help`}>
            O lembrete usa WhatsApp e só é criado para quem se inscreveu neste evento.
          </p>
        </div>

        <fieldset
          className="field"
          aria-describedby={
            publicoError ? `${id}-reminder-audience-error` : `${id}-reminder-audience-help`
          }
          aria-invalid={publicoError || undefined}
        >
          <legend>Público elegível para o lembrete</legend>
          {PUBLICOS_ALVO.map((publico) => (
            <label className="check-row" key={publico}>
              <input
                type="checkbox"
                checked={publicos.has(publico)}
                aria-invalid={publicoError || undefined}
                onChange={() => togglePublico(publico)}
              />
              <span>{PUBLICO_ALVO_LABEL[publico]}</span>
            </label>
          ))}
          <p className="helper" id={`${id}-reminder-audience-help`}>
            Consentimento, opt-out e elegibilidade para lembretes no WhatsApp são verificados
            novamente antes da entrega.
          </p>
          {publicoError ? (
            <p className="err" id={`${id}-reminder-audience-error`} role="alert">
              Selecione ao menos um público para configurar a janela do lembrete.
            </p>
          ) : null}
        </fieldset>

        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="ev-desc">Descrição</label>
          <textarea
            id="ev-desc"
            rows={3}
            value={descricao}
            onChange={(e) => setDescricao(e.target.value)}
            placeholder="Detalhes do evento (opcional)"
          />
        </div>

        <div className="modal-foot">
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Salvando…">
            {isEdit ? "Salvar alterações" : "Salvar evento"}
          </Button>
        </div>
      </form>
    </DsDialog>
  );
}
