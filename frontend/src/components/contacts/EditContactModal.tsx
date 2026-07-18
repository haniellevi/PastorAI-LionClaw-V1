"use client";

/**
 * Edição dos dados cadastrais de uma pessoa (somente admin — gated no backend
 * por PATCH /contacts/{id}). Envia apenas os campos alterados. Mudar o telefone
 * re-checa duplicidade na igreja (409 propagado como erro inline).
 */
import { useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import type { Contact, UpdateContactInput } from "@/lib/contacts-api";

// "Líder" saiu dos tipos manuais: líder de célula é derivado do vínculo com
// célula ativa (regra 2026-07-06); a aptidão (Reencontro) é o toggle abaixo.
const TIPOS = [
  { value: "contato", label: "Contato" },
  { value: "visitante", label: "Visitante" },
  { value: "discipulo", label: "Discípulo" },
  { value: "membro", label: "Membro" },
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
  const [semInteresse, setSemInteresse] = useState(contact.semInteresse);
  const [csimMotivo, setCsimMotivo] = useState(contact.semInteresseMotivo ?? "");
  const [aptoLider, setAptoLider] = useState(contact.aptoLider);
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
    // CSIM: marca/desmarca + motivo (só envia o que mudou).
    if (semInteresse !== contact.semInteresse) input.semInteresse = semInteresse;
    const motivoNorm = csimMotivo.trim() || null;
    if (semInteresse && motivoNorm !== (contact.semInteresseMotivo ?? null)) {
      input.semInteresseMotivo = motivoNorm;
    }
    // Aptidão (Reencontro): CSIM nunca é apto — força false ao marcar CSIM.
    const aptoFinal = semInteresse ? false : aptoLider;
    if (aptoFinal !== contact.aptoLider) input.aptoLider = aptoFinal;
    if (Object.keys(input).length === 0) {
      onClose();
      return;
    }
    onSubmit(input);
  };

  return (
    // W5A: shell manual → DsDialog (Esc/trap/backdrop/retorno de foco do
    // primitive); fechar bloqueado enquanto salva. O foco inicial vai para o
    // campo Nome via [data-autofocus].
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Editar pessoa"
    >
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
            data-autofocus=""
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
              <select
                id="ec-tipo"
                value={semInteresse ? "csim" : tipo}
                onChange={(e) => {
                  const v = e.target.value;
                  // "csim" é um valor virtual do select: liga o flag
                  // sem_interesse e mantém o tipo real por baixo.
                  if (v === "csim") {
                    setSemInteresse(true);
                    setAptoLider(false); // CSIM fica fora da visão: nunca apto
                  } else {
                    setSemInteresse(false);
                    setTipo(v);
                  }
                }}
              >
                <option value="">—</option>
                {TIPOS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
                <option value="csim">Sem interesse (CSIM)</option>
              </select>
            </div>
          </div>

          {semInteresse ? (
            <Field
              label="Motivo (CSIM)"
              value={csimMotivo}
              onChange={(e) => setCsimMotivo(e.target.value)}
              placeholder="ex.: empresa, outra cidade"
            />
          ) : null}

          {/* Aptidão (Reencontro) — modal já é admin-only; CSIM não pode ser apto. */}
          <div className="field">
            <label className="check-row">
              <input
                type="checkbox"
                checked={aptoLider && !semInteresse}
                disabled={busy || semInteresse}
                onChange={(e) => setAptoLider(e.target.checked)}
              />
              <span>Apto a liderar (Reencontro)</span>
            </label>
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
    </DsDialog>
  );
}
