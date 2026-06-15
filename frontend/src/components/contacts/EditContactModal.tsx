"use client";

/**
 * Edição dos dados cadastrais de uma pessoa (somente admin — gated no backend
 * por PATCH /contacts/{id}). Envia apenas os campos alterados. Mudar o telefone
 * re-checa duplicidade na igreja (409 propagado como erro inline).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { Contact, UpdateContactInput } from "@/lib/contacts-api";

const TIPOS = [
  { value: "visitante", label: "Visitante" },
  { value: "discipulo", label: "Discípulo" },
  { value: "membro", label: "Membro" },
  { value: "lider", label: "Líder" },
  { value: "pastor", label: "Pastor" },
];

export interface EditContactModalProps {
  contact: Contact;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: UpdateContactInput) => void;
}

export function EditContactModal({ contact, busy, error, onClose, onSubmit }: EditContactModalProps) {
  const [nome, setNome] = useState(contact.nome);
  const [telefone, setTelefone] = useState(contact.telefone);
  const [email, setEmail] = useState(contact.email ?? "");
  const [genero, setGenero] = useState<"" | "m" | "f">(
    contact.genero === "m" || contact.genero === "f" ? contact.genero : "",
  );
  const [tipo, setTipo] = useState(contact.tipo ?? "");
  const [touched, setTouched] = useState(false);

  const nomeError = touched && !nome.trim() ? "Informe o nome." : undefined;
  const telError =
    touched && telefone.replace(/\D/g, "").length < 8 ? "Telefone inválido." : undefined;

  const submit = () => {
    setTouched(true);
    if (!nome.trim() || telefone.replace(/\D/g, "").length < 8) return;
    // PATCH: envia só o que mudou.
    const input: UpdateContactInput = {};
    if (nome.trim() !== contact.nome) input.nome = nome.trim();
    if (telefone.trim() !== contact.telefone) input.telefone = telefone.trim();
    if ((email.trim() || null) !== (contact.email ?? null)) input.email = email.trim() || null;
    if ((genero || null) !== (contact.genero ?? null)) {
      input.genero = (genero || null) as "m" | "f" | null;
    }
    if ((tipo || null) !== (contact.tipo ?? null)) input.tipo = tipo || null;
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
        aria-label={`Editar ${contact.nome}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Editar pessoa</strong>
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
            error={nomeError}
            autoFocus
          />
          <Field
            label="Telefone"
            value={telefone}
            onChange={(e) => setTelefone(e.target.value)}
            error={telError}
            inputMode="tel"
            helper="Mudar o telefone re-verifica duplicidade na igreja."
          />
          <Field
            label="E-mail"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="opcional"
          />

          <div className="row">
            <div className="field">
              <label htmlFor="ec-genero">Gênero</label>
              <select
                id="ec-genero"
                value={genero}
                onChange={(e) => setGenero(e.target.value as "" | "m" | "f")}
              >
                <option value="">Não informar</option>
                <option value="f">Feminino</option>
                <option value="m">Masculino</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="ec-tipo">Tipo</label>
              <select id="ec-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)}>
                <option value="">—</option>
                {TIPOS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Salvando…">
              Salvar alterações
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
