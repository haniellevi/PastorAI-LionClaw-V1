"use client";

/**
 * US-03 — indicar (nominalmente) um visitante para a próxima reunião. Formulário
 * controlado à mão: nome obrigatório (validação inline) e um pedido de oração
 * opcional. Envia via indicateVisitor (RegisterExpectativaRequest, camelCase).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { indicateVisitor } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

export function IndicateVisitorModal({
  token,
  reuniaoId,
  onClose,
  onToast,
  onIndicated,
}: {
  token: string;
  reuniaoId: string;
  onClose: () => void;
  onToast: FlashToast;
  onIndicated?: (nome: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [oracao, setOracao] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const title = "Indicar visitante";

  async function submit() {
    const trimmed = nome.trim();
    if (!trimmed) {
      setError("Informe o nome do visitante.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await indicateVisitor(token, reuniaoId, {
        nomeVisitante: trimmed,
        observacaoOracao: oracao.trim() || null,
      });
      onToast({ kind: "ok", text: `Visitante indicado: ${created.nome_visitante}.` });
      onIndicated?.(created.nome_visitante);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Não foi possível indicar o visitante.",
      );
    } finally {
      setBusy(false);
    }
  }

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
        <div className="modal-sub">
          Avise a liderança de quem você quer trazer para a próxima reunião.
        </div>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Field
            label="Nome do visitante"
            placeholder="Ex.: Maria Silva"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            disabled={busy}
            autoFocus
            maxLength={120}
          />
          <div className="field">
            <label htmlFor="visitor-oracao">Pedido de oração (opcional)</label>
            <textarea
              id="visitor-oracao"
              rows={3}
              value={oracao}
              onChange={(e) => setOracao(e.target.value)}
              disabled={busy}
              maxLength={500}
              placeholder="Algo pelo que orar por essa pessoa"
            />
          </div>

          <div className="modal-foot">
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={busy}
              loadingText="Enviando…"
              disabled={!nome.trim()}
            >
              <Icon name="plus" />
              <span>Indicar</span>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
