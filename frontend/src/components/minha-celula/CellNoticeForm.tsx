"use client";

/**
 * US-12A — publicar aviso da PRÓPRIA célula (líder). Escopo fixo 'celula' + a
 * célula do líder; nunca broadcast de igreja (isso é da Central). Título e
 * conteúdo controlados à mão. Sucesso: toast "Aviso publicado." e onPublished()
 * para o feed recarregar. Sem edição de aviso no MVP (inativa + cria outro).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { createNotice } from "@/lib/cell-notices-api";
import type { FlashToast } from "./types";

export function CellNoticeForm({
  token,
  cellId,
  onToast,
  onPublished,
}: {
  token: string;
  cellId: string;
  onToast: FlashToast;
  onPublished: () => void;
}) {
  const [titulo, setTitulo] = useState("");
  const [conteudo, setConteudo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function publish() {
    const t = titulo.trim();
    const c = conteudo.trim();
    if (!t || !c) {
      setError("Informe título e conteúdo do aviso.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createNotice(token, {
        titulo: t,
        conteudo: c,
        escopo: "celula",
        celula_id: cellId,
      });
      onToast({ kind: "ok", text: "Aviso publicado." });
      setTitulo("");
      setConteudo("");
      onPublished();
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível publicar o aviso.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Publicar aviso">
      <div className="panel-title">
        <Icon name="bell" /> Publicar aviso
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      <form
        className="section-body"
        onSubmit={(e) => {
          e.preventDefault();
          void publish();
        }}
      >
        <p className="muted-note">Visível apenas para os discípulos da sua célula.</p>
        <Field
          label="Título"
          placeholder="Ex.: Reunião especial no sábado"
          value={titulo}
          onChange={(e) => setTitulo(e.target.value)}
          disabled={busy}
          maxLength={120}
        />
        <div className="field">
          <label htmlFor={`notice-conteudo-${cellId}`}>Conteúdo</label>
          <textarea
            id={`notice-conteudo-${cellId}`}
            rows={3}
            value={conteudo}
            onChange={(e) => setConteudo(e.target.value)}
            disabled={busy}
            maxLength={1000}
            placeholder="Escreva o aviso para a célula."
          />
        </div>
        <div className="section-actions">
          <Button
            type="submit"
            variant="default"
            size="sm"
            loading={busy}
            loadingText="Publicando…"
            disabled={!titulo.trim() || !conteudo.trim()}
          >
            <Icon name="send" />
            <span>Publicar aviso</span>
          </Button>
        </div>
      </form>
    </section>
  );
}
