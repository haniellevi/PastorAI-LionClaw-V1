"use client";

/**
 * US-11 — enviar (consolidar) o relatório da reunião (líder). Aguarda o servidor
 * com loading NO BOTÃO (não otimista): ao concluir, toast "Relatório enviado." e
 * a UI passa a bloquear edição. 409 (relatório já enviado / reunião incompatível)
 * vira toast explicativo, sem quebrar a tela.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { submitReport, MeetingConflictError } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

export function SubmitReportButton({
  token,
  reuniaoId,
  onToast,
  onSubmitted,
}: {
  token: string;
  reuniaoId: string;
  onToast: FlashToast;
  onSubmitted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await submitReport(token, reuniaoId);
      onToast({ kind: "ok", text: "Relatório enviado." });
      onSubmitted();
    } catch (err) {
      const text =
        err instanceof MeetingConflictError
          ? err.message
          : err instanceof ApiError
            ? err.message
            : "Não foi possível enviar o relatório.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Enviar relatório">
      <div className="section-body">
        <p className="muted-note">
          Ao enviar, o relatório é consolidado e <strong>bloqueado para edição</strong>.
          Confira presença, visitantes, registros e oferta antes de confirmar.
        </p>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="section-actions">
          <Button
            variant="primary"
            size="md"
            block
            onClick={() => void submit()}
            loading={busy}
            loadingText="Enviando…"
          >
            <Icon name="send" />
            <span>Enviar relatório</span>
          </Button>
        </div>
      </div>
    </section>
  );
}
