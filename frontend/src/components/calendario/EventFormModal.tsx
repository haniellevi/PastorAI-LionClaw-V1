"use client";

/**
 * Form de evento da agenda (api-events) — form-field + btn-primary. Cria um novo
 * evento ou, quando recebe `event` (EVT-4), edita um existente (PUT parcial). O
 * backend tenta espelhar no Google Calendar na criação; se o sync falhar, o
 * evento é salvo local e devolvido como não sincronizado (a tela sinaliza para
 * re-tentar). A edição não re-sincroniza (escopo EVT-6+).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { CreateEventInput, EventItem } from "@/lib/events-api";

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
  const [titulo, setTitulo] = useState(event?.titulo ?? "");
  const [data, setData] = useState(event?.data ?? defaultDate ?? "");
  const [hora, setHora] = useState(event?.hora ?? "");
  const [descricao, setDescricao] = useState(event?.descricao ?? "");
  const [touched, setTouched] = useState(false);

  const tituloError = touched && !titulo.trim() ? "Informe o título." : undefined;
  const dataError = touched && !data ? "Escolha a data." : undefined;

  const submit = () => {
    setTouched(true);
    if (!titulo.trim() || !data) return;
    onSubmit({
      titulo: titulo.trim(),
      data,
      hora: hora || null,
      descricao: descricao.trim() || null,
    });
  };

  const title = isEdit ? "Editar evento" : "Novo evento";

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
              <span>{error}</span>
            </div>
          ) : null}

          <Field
            label="Título"
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            placeholder="Ex.: Culto de domingo"
            error={tituloError}
            autoFocus
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
      </div>
    </div>
  );
}
