"use client";

/**
 * Provisionar nova igreja (US-43): cria o tenant + admin inicial (que recebe o
 * convite de ativação por e-mail). Validação inline; o erro do backend (422 de
 * plano inválido, etc.) é exibido no banner.
 *
 * Wave Visual W4B: migração para o DsDialog (Esc/trap/backdrop/scroll-lock/
 * retorno de foco do primitive; fechar bloqueado em busy) — mesmos campos,
 * callbacks e textos. O rodapé fica fora do <form>, então o botão primário usa
 * form="create-igreja-form" para preservar o submit por Enter.
 */
import { useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { isInvalidSetupFee, type CreateIgrejaInput } from "@/lib/admin-api";

/** Planos oferecidos no seletor (vêm do catálogo; fallback p/ os 3 padrão). */
export interface PlanoOption {
  codigo: string;
  nome: string;
}

const FALLBACK_PLANOS: PlanoOption[] = [
  { codigo: "ate_100", nome: "Até 100 pessoas" },
  { codigo: "101_200", nome: "101–200 pessoas" },
  { codigo: "acima_201", nome: "201+ pessoas" },
];

export interface CreateIgrejaModalProps {
  busy: boolean;
  error: string | null;
  planos?: PlanoOption[];
  onClose: () => void;
  onSubmit: (input: CreateIgrejaInput) => void;
}

export function CreateIgrejaModal({
  busy,
  error,
  planos,
  onClose,
  onSubmit,
}: CreateIgrejaModalProps) {
  const planOptions = planos && planos.length ? planos : FALLBACK_PLANOS;
  const [nome, setNome] = useState("");
  const [plano, setPlano] = useState("");
  const [setupFeeOverride, setSetupFeeOverride] = useState("");
  const [adminNome, setAdminNome] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [touched, setTouched] = useState(false);

  const nomeError = touched && !nome.trim() ? "Informe o nome da igreja." : undefined;
  const adminNomeError =
    touched && !adminNome.trim() ? "Informe o nome do administrador." : undefined;
  const adminEmailError =
    touched && !adminEmail.includes("@") ? "Informe um e-mail válido." : undefined;
  const setupFeeValue =
    setupFeeOverride.trim() === "" ? null : Number(setupFeeOverride);
  const setupFeeInvalid = setupFeeValue !== null && isInvalidSetupFee(setupFeeValue);
  const setupFeeError =
    touched && setupFeeInvalid
      ? "Taxa de setup deve ser R$ 0,00 (isenta) ou de pelo menos R$ 5,00."
      : undefined;

  const submit = () => {
    setTouched(true);
    if (!nome.trim() || !adminNome.trim() || !adminEmail.includes("@") || setupFeeInvalid)
      return;
    onSubmit({
      nome: nome.trim(),
      plano: plano || null,
      setupFeeOverride: setupFeeValue,
      admin: { nome: adminNome.trim(), email: adminEmail.trim() },
    });
  };

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Provisionar nova igreja"
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <Button
            type="submit"
            form="create-igreja-form"
            variant="primary"
            size="sm"
            loading={busy}
            loadingText="Provisionando…"
          >
            Provisionar igreja
          </Button>
        </>
      }
    >
      <form
        id="create-igreja-form"
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
          label="Nome da igreja"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="Ex.: Igreja Batista Central"
          error={nomeError}
          data-autofocus=""
        />

        <div className="field">
          <label htmlFor="ci-plano">Plano</label>
          <select id="ci-plano" value={plano} onChange={(e) => setPlano(e.target.value)}>
            <option value="">Sem plano definido</option>
            {planOptions.map((p) => (
              <option key={p.codigo} value={p.codigo}>
                {p.nome}
              </option>
            ))}
          </select>
        </div>

        <Field
          label="Taxa de setup personalizada (R$)"
          type="number"
          min={0}
          step="0.01"
          value={setupFeeOverride}
          onChange={(e) => setSetupFeeOverride(e.target.value)}
          placeholder="Use a taxa padrão"
          helper="Deixe vazio para usar a taxa padrão definida no painel master."
          error={setupFeeError}
        />

        <Field
          label="Administrador — nome"
          value={adminNome}
          onChange={(e) => setAdminNome(e.target.value)}
          placeholder="Nome do pastor/responsável"
          error={adminNomeError}
        />
        <Field
          label="Administrador — e-mail"
          type="email"
          value={adminEmail}
          onChange={(e) => setAdminEmail(e.target.value)}
          placeholder="admin@igreja.com.br"
          helper="Recebe o convite para ativar o acesso ao painel da igreja."
          error={adminEmailError}
        />
      </form>
    </DsDialog>
  );
}
