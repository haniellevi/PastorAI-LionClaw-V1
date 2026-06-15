"use client";

/**
 * Provisionar nova igreja (US-43): cria o tenant + admin inicial (que recebe o
 * convite de ativação por e-mail). Validação inline; o erro do backend (422 de
 * plano inválido, etc.) é exibido no banner. Segue o padrão de modal do projeto.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { CreateIgrejaInput } from "@/lib/admin-api";

const PLANOS = [
  { value: "", label: "Sem plano definido" },
  { value: "ate_100", label: "Até 100 pessoas" },
  { value: "101_200", label: "101–200 pessoas" },
  { value: "acima_201", label: "201+ pessoas" },
];

export interface CreateIgrejaModalProps {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: CreateIgrejaInput) => void;
}

export function CreateIgrejaModal({ busy, error, onClose, onSubmit }: CreateIgrejaModalProps) {
  const [nome, setNome] = useState("");
  const [plano, setPlano] = useState("");
  const [adminNome, setAdminNome] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [touched, setTouched] = useState(false);

  const nomeError = touched && !nome.trim() ? "Informe o nome da igreja." : undefined;
  const adminNomeError =
    touched && !adminNome.trim() ? "Informe o nome do administrador." : undefined;
  const adminEmailError =
    touched && !adminEmail.includes("@") ? "Informe um e-mail válido." : undefined;

  const submit = () => {
    setTouched(true);
    if (!nome.trim() || !adminNome.trim() || !adminEmail.includes("@")) return;
    onSubmit({
      nome: nome.trim(),
      plano: plano || null,
      admin: { nome: adminNome.trim(), email: adminEmail.trim() },
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Provisionar igreja"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Provisionar nova igreja</strong>
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
            label="Nome da igreja"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Ex.: Igreja Batista Central"
            error={nomeError}
            autoFocus
          />

          <div className="field">
            <label htmlFor="ci-plano">Plano</label>
            <select id="ci-plano" value={plano} onChange={(e) => setPlano(e.target.value)}>
              {PLANOS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

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

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Provisionando…"
            >
              Provisionar igreja
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
