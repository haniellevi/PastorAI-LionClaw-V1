"use client";

/**
 * Formulário de novo contato (api-create-contact) — form-field + btn-primary.
 * Telefone duplicado não cria duplicata: o backend retorna deduped=true e o
 * contato existente; a tela avisa e aponta para ele. Falha ao salvar mantém o
 * formulário preenchido com erro inline.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { CreateContactInput } from "@/lib/contacts-api";

export interface NewContactModalProps {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: CreateContactInput) => void;
}

export function NewContactModal({ busy, error, onClose, onSubmit }: NewContactModalProps) {
  const [nome, setNome] = useState("");
  const [telefone, setTelefone] = useState("");
  const [email, setEmail] = useState("");
  const [genero, setGenero] = useState<"" | "m" | "f">("");
  const [tipo, setTipo] = useState("contato");
  const [touched, setTouched] = useState(false);

  const nomeError = touched && !nome.trim() ? "Informe o nome." : undefined;
  const telError =
    touched && telefone.replace(/\D/g, "").length < 8 ? "Telefone inválido." : undefined;

  const submit = () => {
    setTouched(true);
    if (!nome.trim() || telefone.replace(/\D/g, "").length < 8) return;
    onSubmit({
      nome: nome.trim(),
      telefone: telefone.trim(),
      email: email.trim() || null,
      genero: genero || null,
      tipo: tipo || null,
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Novo contato"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Novo contato</strong>
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
            label="Nome"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Nome completo"
            error={nomeError}
            autoFocus
          />
          <Field
            label="Telefone"
            value={telefone}
            onChange={(e) => setTelefone(e.target.value)}
            placeholder="+55 89 99999-0000"
            helper="Usado para deduplicar contatos na igreja."
            error={telError}
            inputMode="tel"
          />
          <Field
            label="E-mail"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="opcional"
            type="email"
          />

          <div className="row">
            <div className="field">
              <label htmlFor="nc-genero">Gênero</label>
              <select
                id="nc-genero"
                value={genero}
                onChange={(e) => setGenero(e.target.value as "" | "m" | "f")}
              >
                <option value="">Não informar</option>
                <option value="f">Feminino</option>
                <option value="m">Masculino</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="nc-tipo">Tipo</label>
              <select id="nc-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)}>
                <option value="contato">Contato</option>
                <option value="visitante">Visitante</option>
                <option value="membro">Membro</option>
                <option value="discipulo">Discípulo</option>
                <option value="lider">Líder</option>
                <option value="pastor">Pastor</option>
              </select>
            </div>
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Salvando…">
              Salvar contato
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
