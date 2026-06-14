"use client";

/**
 * Comunicar líderes em massa (api-broadcasts, segmento `lider`). Compõe uma
 * mensagem e envia pelo WhatsApp oficial. O backend remove opt-out/sem
 * consentimento e devolve enviados/ignorados; alcance limpo zero bloqueia o
 * envio (status=bloqueado) — refletido aqui com a contagem de ignorados.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { createBroadcast, type BroadcastResult } from "@/lib/broadcasts-api";
import { ApiError } from "@/lib/dashboard-api";

export function CommunicateLeadersModal({
  token,
  leaderCount,
  onClose,
  onSent,
}: {
  token: string;
  leaderCount: number;
  onClose: () => void;
  onSent: (result: BroadcastResult) => void;
}) {
  const [titulo, setTitulo] = useState("Material para líderes");
  const [mensagem, setMensagem] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  const msgError = touched && !mensagem.trim() ? "Escreva a mensagem." : undefined;

  const submit = async () => {
    setTouched(true);
    if (!titulo.trim() || !mensagem.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createBroadcast(token, {
        titulo: titulo.trim(),
        mensagem: mensagem.trim(),
        segmentos: ["lider"],
        modo: "agora",
      });
      onSent(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Não foi possível enviar o material.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Comunicar líderes"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Enviar material aos líderes</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="cl-titulo">Título interno</label>
            <input
              id="cl-titulo"
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
              placeholder="Ex.: Material da reunião de líderes"
            />
          </div>

          <div className={`field${msgError ? " invalid" : ""}`} style={{ marginBottom: 0 }}>
            <label htmlFor="cl-msg">Mensagem</label>
            <textarea
              id="cl-msg"
              rows={4}
              value={mensagem}
              onChange={(e) => setMensagem(e.target.value)}
              placeholder="Escreva o que será enviado aos líderes…"
            />
            {msgError ? (
              <div className="err" role="alert">{msgError}</div>
            ) : (
              <div className="helper">
                Será enviado a {leaderCount} líder(es) pelo WhatsApp oficial. Opt-out
                e contatos sem consentimento são removidos automaticamente.
              </div>
            )}
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Enviando…">
              Enviar material
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
