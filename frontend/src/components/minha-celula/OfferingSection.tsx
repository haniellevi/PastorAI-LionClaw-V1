"use client";

/**
 * US-10 — oferta e observações gerais do relatório (líder). Salva como RASCUNHO
 * via saveReport (não envia): valor da oferta (>= 0, até 999999.99) e observações
 * livres (até 2000). Toast "Relatório salvo." confirma o rascunho. Bloqueado após
 * o relatório enviado (E10/E11).
 */
import { useState } from "react";

import { DsButton } from "@/components/ds/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { saveReport } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

const VALUE_RE = /^\d{0,6}([.,]\d{0,2})?$/;

export function OfferingSection({
  token,
  reuniaoId,
  ofertaValor,
  observacoes,
  locked,
  onToast,
  onSaved,
}: {
  token: string;
  reuniaoId: string;
  ofertaValor: number | null;
  observacoes: string | null;
  locked: boolean;
  onToast: FlashToast;
  onSaved: () => void;
}) {
  const [valor, setValor] = useState(
    ofertaValor != null ? String(ofertaValor).replace(".", ",") : "",
  );
  const [obs, setObs] = useState(observacoes ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = valor.trim() ? Number(valor.trim().replace(",", ".")) : null;
  const valorError =
    valor.trim() && (!VALUE_RE.test(valor.trim()) || parsed == null || Number.isNaN(parsed))
      ? "Informe um valor válido (ex.: 120,50)."
      : parsed != null && parsed > 999999.99
        ? "Valor máximo: 999999,99."
        : undefined;

  async function save() {
    if (valorError) return;
    setBusy(true);
    setError(null);
    try {
      await saveReport(token, reuniaoId, {
        oferta_valor: parsed,
        observacoes: obs.trim() || null,
      });
      onToast({ kind: "ok", text: "Relatório salvo." });
      onSaved();
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível salvar o relatório.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mc-report-section-content mc-report-closing-fields">
      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="section-body">
        <Field
          label="Oferta (R$)"
          placeholder="Ex.: 120,50"
          value={valor}
          onChange={(e) => setValor(e.target.value)}
          error={valorError}
          disabled={locked || busy}
          inputMode="decimal"
          maxLength={10}
        />
        <div className="field">
          <label htmlFor={`rep-obs-${reuniaoId}`}>Observações gerais</label>
          <textarea
            id={`rep-obs-${reuniaoId}`}
            rows={3}
            value={obs}
            onChange={(e) => setObs(e.target.value)}
            disabled={locked || busy}
            maxLength={2000}
            placeholder="Como foi a reunião, pedidos, encaminhamentos…"
          />
        </div>

        {!locked ? (
          <div className="section-actions">
            <DsButton
              variant="primary"
              onClick={() => void save()}
              loading={busy}
              disabled={Boolean(valorError)}
            >
              <Icon name="check" />
              <span>{busy ? "Salvando rascunho…" : "Salvar rascunho"}</span>
            </DsButton>
          </div>
        ) : null}
      </div>
    </div>
  );
}
