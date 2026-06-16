"use client";

/**
 * Modal de convite a partir do detalhe da célula (#celulas — delta-049).
 *
 * O líder da célula (ou admin/pastor) convida uma pessoa JÁ cadastrada e ainda
 * SEM célula para ESTA célula: ela entra como membro e recebe acesso ao painel
 * por e-mail. O backend valida a autoria (um líder só convida para a célula que
 * lidera — 403 caso contrário) e a trava de célula única.
 */
import { useMemo, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { inviteMember, TeamConflictError } from "@/lib/team-api";

interface Props {
  celulaId: string;
  celulaNome: string;
  contacts: Contact[];
  onClose: () => void;
  onInvited: (text: string) => void;
}

export function InviteMemberModal({ celulaId, celulaNome, contacts, onClose, onInvited }: Props) {
  const { token, expireSession } = useAuth();
  const [query, setQuery] = useState("");
  const [pessoaId, setPessoaId] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [needsEmail, setNeedsEmail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Candidatos: pessoas que ainda não estão em nenhuma célula (regra de célula
  // única — quem já tem célula só pode ser transferido por um admin, à parte).
  const candidatos = useMemo(() => {
    const q = query.trim().toLowerCase();
    const semCelula = contacts.filter((c) => !c.celulaId);
    const base = q
      ? semCelula.filter((c) =>
          `${c.nome} ${c.telefone} ${c.email ?? ""}`.toLowerCase().includes(q),
        )
      : semCelula;
    return base.slice(0, 50);
  }, [contacts, query]);

  const select = (c: Contact) => {
    setPessoaId(c.id);
    setEmail(c.email ?? "");
    setNeedsEmail(!(c.email ?? "").trim());
    setError(null);
  };

  const emailValid = (e: string) => /\S+@\S+\.\S+/.test(e.trim());
  const ready = pessoaId !== null && emailValid(email);

  async function submit() {
    if (!token || !ready || !pessoaId) return;
    setSending(true);
    setError(null);
    try {
      const dest = email.trim().toLowerCase();
      const r = await inviteMember(token, { pessoaId, email: dest, celulaId });
      onInvited(
        r.emailEnviado
          ? `Convite enviado para ${dest}.`
          : "Acesso criado, mas o e-mail de convite não saiu (e-mail não configurado no servidor).",
      );
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      if (err instanceof TeamConflictError) {
        setError(err.message);
      } else {
        setError(err instanceof ApiError ? err.message : "Não foi possível enviar o convite.");
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Convidar membro para ${celulaNome}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Convidar membro · {celulaNome}</strong>
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
              <Icon name="alert" />
              <span>{error}</span>
            </div>
          ) : null}
          <p className="sub" style={{ color: "var(--muted)" }}>
            O convidado entra como <strong>membro</strong> desta célula e recebe acesso
            ao painel por e-mail. Aparecem só pessoas que ainda não estão em célula —
            cadastre em Contatos se faltar alguém.
          </p>

          <div className="field">
            <label htmlFor="invCellQuery">Pessoa</label>
            <input
              id="invCellQuery"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nome, telefone ou e-mail…"
              autoFocus
            />
            <div
              style={{
                maxHeight: 220,
                overflowY: "auto",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-md)",
                marginTop: 6,
              }}
            >
              {candidatos.length === 0 ? (
                <p className="sub" style={{ color: "var(--muted)", padding: "var(--s3)" }}>
                  Nenhuma pessoa sem célula encontrada.
                </p>
              ) : (
                candidatos.map((c) => {
                  const sel = pessoaId === c.id;
                  return (
                    <button
                      type="button"
                      key={c.id}
                      onClick={() => select(c)}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 8,
                        width: "100%",
                        textAlign: "left",
                        padding: "8px 12px",
                        background: sel ? "var(--accent-soft)" : "transparent",
                        border: "none",
                        borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        font: "inherit",
                        color: "inherit",
                      }}
                    >
                      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                        <span className="nm">{c.nome}</span>
                        <span className="sub mono" style={{ color: "var(--muted)" }}>
                          {c.telefone}
                          {c.email ? ` · ${c.email}` : " · sem e-mail"}
                        </span>
                      </span>
                      {sel ? <StatusPill tone="accent">Selecionada</StatusPill> : null}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {pessoaId && needsEmail ? (
            <div className="field">
              <label htmlFor="invCellEmail">
                E-mail para login{" "}
                <span className="sub" style={{ color: "var(--muted)", fontWeight: 400 }}>
                  — esta pessoa ainda não tem e-mail cadastrado
                </span>
              </label>
              <input
                id="invCellEmail"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="membro@igreja.com.br"
              />
            </div>
          ) : null}

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={sending}>
              Cancelar
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={!ready || sending}
              aria-busy={sending || undefined}
            >
              {sending ? "Enviando…" : "Enviar convite"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
