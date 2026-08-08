"use client";

/**
 * Alterar status e/ou plano de uma igreja (US-42): suspender, reativar, aprovar
 * ou mover de plano. Envia só os campos alterados. Observação: o backend não
 * aceita "limpar" o plano (apenas trocar por um plano válido), então selecionar
 * "Sem plano definido" quando já há plano não tem efeito.
 *
 * Wave Visual W4B: migração para o DsDialog (Esc/trap/backdrop/scroll-lock/
 * retorno de foco do primitive; fechar bloqueado em busy) — mesmos campos,
 * callbacks e textos. A zona destrutiva (aviso + window.confirm + onDelete)
 * segue no corpo; o rodapé fica fora do <form>, então o botão primário usa
 * form="edit-igreja-form" para preservar o submit por Enter.
 */
import { useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { isInvalidSetupFee, type AdminIgreja, type UpdateIgrejaInput } from "@/lib/admin-api";
import type { PlanoOption } from "./CreateIgrejaModal";

const STATUSES = [
  { value: "ativa", label: "Ativa" },
  { value: "suspensa", label: "Suspensa" },
  { value: "aguardando_aprovacao", label: "Aguardando aprovação" },
  { value: "inadimplente", label: "Inadimplente" },
];

const FALLBACK_PLANOS: PlanoOption[] = [
  { codigo: "ate_100", nome: "Até 100 membros" },
  { codigo: "101_200", nome: "101–200 membros" },
  { codigo: "acima_201", nome: "201+ membros" },
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
  const [nome, setNome] = useState(igreja.nome);
  const [status, setStatus] = useState(igreja.status);
  const [plano, setPlano] = useState(igreja.plano ?? "");
  const [setupFeeOverride, setSetupFeeOverride] = useState(
    igreja.setupFeeOverride == null ? "" : String(igreja.setupFeeOverride),
  );
  const [setupFeeError, setSetupFeeError] = useState<string | null>(null);

  const base = planos && planos.length ? planos : FALLBACK_PLANOS;
  // Garante que o plano atual apareça no seletor mesmo se já estiver inativo
  // (igreja grandfathered num plano que o master desativou).
  const planOptions =
    igreja.plano && !base.some((p) => p.codigo === igreja.plano)
      ? [...base, { codigo: igreja.plano, nome: `${igreja.plano} (inativo)` }]
      : base;

  const submit = () => {
    const input: UpdateIgrejaInput = {};
    const setupFeeValue =
      setupFeeOverride.trim() === "" ? null : Number(setupFeeOverride);
    if (setupFeeValue !== null && isInvalidSetupFee(setupFeeValue)) {
      setSetupFeeError("Taxa de setup deve ser R$ 0,00 (isenta) ou de pelo menos R$ 5,00.");
      return;
    }
    setSetupFeeError(null);
    const nomeT = nome.trim();
    if (nomeT && nomeT !== igreja.nome) input.nome = nomeT;
    if (status !== igreja.status) input.status = status;
    // Só envia plano quando há um valor (o backend não aceita limpar plano).
    if (plano && plano !== (igreja.plano ?? "")) input.plano = plano;
    if (setupFeeValue !== igreja.setupFeeOverride) {
      input.setupFeeOverride = setupFeeValue;
    }
    if (Object.keys(input).length === 0) {
      onClose();
      return;
    }
    onSubmit(input);
  };

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={igreja.nome}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <Button
            type="submit"
            form="edit-igreja-form"
            variant="primary"
            size="sm"
            loading={busy}
            loadingText="Salvando…"
          >
            Salvar alterações
          </Button>
        </>
      }
    >
      <form
        id="edit-igreja-form"
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
          <label htmlFor="ei-nome">Nome da igreja</label>
          <input
            id="ei-nome"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Nome da igreja"
            data-autofocus=""
          />
        </div>

        <Field
          label="Taxa de setup personalizada (R$)"
          type="number"
          min={0}
          step="0.01"
          value={setupFeeOverride}
          onChange={(event) => {
            setSetupFeeOverride(event.target.value);
            setSetupFeeError(null);
          }}
          placeholder="Use a taxa padrão"
          helper="Deixe vazio para remover a exceção e usar a taxa padrão do master."
          error={setupFeeError ?? undefined}
        />

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
    </DsDialog>
  );
}
