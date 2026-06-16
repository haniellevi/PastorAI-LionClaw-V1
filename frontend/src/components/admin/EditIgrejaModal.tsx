"use client";

/**
 * Alterar status e/ou plano de uma igreja (US-42): suspender, reativar, aprovar
 * ou mover de plano. Envia só os campos alterados. Observação: o backend não
 * aceita "limpar" o plano (apenas trocar por um plano válido), então selecionar
 * "Sem plano definido" quando já há plano não tem efeito.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { AdminIgreja, UpdateIgrejaInput } from "@/lib/admin-api";
import type { PlanoOption } from "./CreateIgrejaModal";

const STATUSES = [
  { value: "ativa", label: "Ativa" },
  { value: "suspensa", label: "Suspensa" },
  { value: "aguardando_aprovacao", label: "Aguardando aprovação" },
  { value: "inadimplente", label: "Inadimplente" },
];

const FALLBACK_PLANOS: PlanoOption[] = [
  { codigo: "ate_100", nome: "Até 100 pessoas" },
  { codigo: "101_200", nome: "101–200 pessoas" },
  { codigo: "acima_201", nome: "201+ pessoas" },
];

export interface EditIgrejaModalProps {
  igreja: AdminIgreja;
  busy: boolean;
  error: string | null;
  planos?: PlanoOption[];
  onClose: () => void;
  onSubmit: (input: UpdateIgrejaInput) => void;
  onDelete: () => void;
}

export function EditIgrejaModal({
  igreja,
  busy,
  error,
  planos,
  onClose,
  onSubmit,
  onDelete,
}: EditIgrejaModalProps) {
  const [status, setStatus] = useState(igreja.status);
  const [plano, setPlano] = useState(igreja.plano ?? "");

  const base = planos && planos.length ? planos : FALLBACK_PLANOS;
  // Garante que o plano atual apareça no seletor mesmo se já estiver inativo
  // (igreja grandfathered num plano que o master desativou).
  const planOptions =
    igreja.plano && !base.some((p) => p.codigo === igreja.plano)
      ? [...base, { codigo: igreja.plano, nome: `${igreja.plano} (inativo)` }]
      : base;

  const submit = () => {
    const input: UpdateIgrejaInput = {};
    if (status !== igreja.status) input.status = status;
    // Só envia plano quando há um valor (o backend não aceita limpar plano).
    if (plano && plano !== (igreja.plano ?? "")) input.plano = plano;
    if (Object.keys(input).length === 0) {
      onClose();
      return;
    }
    onSubmit(input);
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Editar igreja"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{igreja.nome}</strong>
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

          <div className="field">
            <label htmlFor="ei-status">Status</label>
            <select id="ei-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="ei-plano">Plano</label>
            <select id="ei-plano" value={plano} onChange={(e) => setPlano(e.target.value)}>
              <option value="">Sem plano definido</option>
              {planOptions.map((p) => (
                <option key={p.codigo} value={p.codigo}>
                  {p.nome}
                </option>
              ))}
            </select>
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
              loadingText="Salvando…"
            >
              Salvar alterações
            </Button>
          </div>

          <div
            style={{
              borderTop: "1px solid var(--border)",
              marginTop: "var(--s3)",
              paddingTop: "var(--s3)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "var(--s2)",
            }}
          >
            <span className="sub" style={{ color: "var(--muted)" }}>
              Excluir apaga a igreja e todos os seus dados.
            </span>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    `Excluir a igreja "${igreja.nome}" e TODOS os seus dados? Esta ação é irreversível.`,
                  )
                ) {
                  onDelete();
                }
              }}
            >
              Excluir igreja
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
