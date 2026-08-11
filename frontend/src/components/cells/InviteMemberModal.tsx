"use client";

import { useMemo, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DsBanner } from "@/components/ds/Banner";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { addCellMember } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

interface Props {
  celulaId: string;
  celulaNome: string;
  contacts: Contact[];
  onClose: () => void;
  onAdded: () => void;
}

/**
 * Vincula uma Pessoa já cadastrada à célula. Não cria conta, convite ou acesso
 * ao painel; essa responsabilidade permanece separada na tela de Equipe.
 */
export function AddCellMemberModal({
  celulaId,
  celulaNome,
  contacts,
  onClose,
  onAdded,
}: Props) {
  const { token, expireSession } = useAuth();
  const [query, setQuery] = useState("");
  const [pessoaId, setPessoaId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  const candidatos = useMemo(() => {
    const q = query.trim().toLowerCase();
    const elegiveis = contacts.filter(
      (contact) =>
        !contact.celulaId &&
        !contact.liderDeCelula &&
        contact.tipo !== "pastor" &&
        !contact.semInteresse &&
        !contact.arquivada,
    );
    const base = q
      ? elegiveis.filter((contact) =>
          `${contact.nome} ${contact.telefone}`.toLowerCase().includes(q),
        )
      : elegiveis;
    return base.slice(0, 50);
  }, [contacts, query]);

  const selected = candidatos.find((contact) => contact.id === pessoaId) ?? null;

  async function submit() {
    if (!token || !selected || sending) return;
    setSending(true);
    setError(null);
    try {
      await addCellMember(token, celulaId, selected.id);
      setSuccess(
        `${selected.nome} foi adicionada à célula. O vínculo não cria acesso ao painel.`,
      );
      onAdded();
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "Não foi possível adicionar a pessoa à célula.",
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <DsDialog
      open
      onClose={() => {
        if (!sending) onClose();
      }}
      title={`Adicionar à célula · ${celulaNome}`}
    >
      {success ? (
        <div className="modal-form">
          <DsBanner kind="info">{success}</DsBanner>
          <p className="sub" style={{ color: "var(--muted)" }}>
            Se esta pessoa também precisar entrar no sistema, conceda o acesso
            separadamente em Equipe.
          </p>
          <div className="modal-foot">
            <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
              Concluir
            </button>
          </div>
        </div>
      ) : (
        <form
          className="modal-form"
          onSubmit={(event) => {
            event.preventDefault();
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
            Escolha uma Pessoa já cadastrada. Esta ação apenas cria o vínculo
            com a célula e não concede acesso ao painel.
          </p>

          <div className="field">
            <label htmlFor="addCellMemberQuery">Pessoa</label>
            <input
              id="addCellMemberQuery"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPessoaId(null);
                setError(null);
              }}
              placeholder="Buscar por nome ou telefone…"
              autoFocus
              data-autofocus=""
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
                  Nenhuma Pessoa elegível sem célula foi encontrada.
                </p>
              ) : (
                candidatos.map((contact) => {
                  const isSelected = pessoaId === contact.id;
                  return (
                    <button
                      type="button"
                      key={contact.id}
                      onClick={() => {
                        setPessoaId(contact.id);
                        setError(null);
                      }}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 8,
                        width: "100%",
                        minHeight: 44,
                        textAlign: "left",
                        padding: "8px 12px",
                        background: isSelected ? "var(--accent-soft)" : "transparent",
                        border: "none",
                        borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        font: "inherit",
                        color: "inherit",
                      }}
                    >
                      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                        <span className="nm">{contact.nome}</span>
                        <span className="sub mono" style={{ color: "var(--muted)" }}>
                          {contact.telefone}
                        </span>
                      </span>
                      {isSelected ? <StatusPill tone="accent">Selecionada</StatusPill> : null}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={sending}>
              Cancelar
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={!selected || sending}
              aria-busy={sending || undefined}
            >
              {sending ? "Adicionando…" : "Adicionar à célula"}
            </button>
          </div>
        </form>
      )}
    </DsDialog>
  );
}
