"use client";

import "./operations-ux-v2.css";

import { useEffect, useMemo, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DsBanner } from "@/components/ds/Banner";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { addCellMember } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import type { ContactLookup } from "@/lib/lookup-api";
import { useLookupPage, type LookupLoader } from "@/components/lookups/useLookupPage";
import { LookupPager } from "@/components/lookups/LookupPager";
import { DsButton } from "@/components/ds/Button";

interface Props {
  celulaId: string;
  celulaNome: string;
  contacts: Contact[];
  loadContactsPage?: LookupLoader<ContactLookup>;
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
  loadContactsPage,
  onClose,
  onAdded,
}: Props) {
  const { token, expireSession } = useAuth();
  const [query, setQuery] = useState("");
  const [pessoaId, setPessoaId] = useState<string | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<ContactLookup | null>(null);
  const lookup = useLookupPage(loadContactsPage, query);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  const candidatos = useMemo(() => {
    const q = query.trim().toLowerCase();
    const elegiveis = (loadContactsPage ? lookup.result?.items ?? [] : contacts).filter(
      (contact) =>
        !contact.celulaId &&
        !contact.liderDeCelula &&
        contact.tipo !== "pastor" &&
        !contact.semInteresse &&
        !contact.arquivada,
    );
    const base = q && !loadContactsPage
      ? elegiveis.filter((contact) =>
          `${contact.nome} ${contact.telefone}`.toLowerCase().includes(q),
        )
      : elegiveis;
    return base;
  }, [contacts, query, loadContactsPage, lookup.result]);

  const selected = selectedPerson?.id === pessoaId ? selectedPerson : null;
  useEffect(() => { if (lookup.error instanceof SessionExpiredError) expireSession(); }, [lookup.error, expireSession]);

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
    <DsDialog className="ops-dialog"
      open
      onClose={() => {
        if (!sending) onClose();
      }}
      title={`Adicionar à célula · ${celulaNome}`}
    >
      {success ? (
        <div className="modal-form ops-dialog">
          <DsBanner kind="info">{success}</DsBanner>
          <p className="sub ds-muted">
            Se esta pessoa também precisar entrar no sistema, conceda o acesso
            separadamente em Equipe.
          </p>
          <div className="modal-foot">
            <DsButton onClick={onClose}>
              Concluir
            </DsButton>
          </div>
        </div>
      ) : (
        <form
          className="modal-form ops-dialog"
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

          <p className="sub ds-muted">
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
                setSelectedPerson(null);
                setError(null);
              }}
              placeholder="Buscar por nome ou telefone…"
              autoFocus
              data-autofocus=""
            />
            <div className="ops-pick-list">
              {loadContactsPage && lookup.loading ? <p className="sub" role="status">Carregando Pessoas…</p> : lookup.error ? <div role="alert">
                {lookup.error instanceof Error ? lookup.error.message : "Não foi possível carregar as Pessoas."}
                <DsButton variant="secondary" onClick={lookup.retry}>Tentar novamente</DsButton>
              </div> : candidatos.length === 0 ? (
                <p className="sub ds-muted ds-p-3">
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
                        setSelectedPerson(contact);
                        setError(null);
                      }}
                      className={`ops-pick-option${isSelected ? " ops-pick-option--selected" : ""}`}
                    >
                      <span className="ops-pick-option-copy">
                        <span className="nm">{contact.nome}</span>
                        <span className="sub mono ds-muted">
                          {contact.telefone}
                        </span>
                      </span>
                      {isSelected ? <StatusPill tone="accent">Selecionada</StatusPill> : null}
                    </button>
                  );
                })
              )}
            </div>
            {loadContactsPage ? <LookupPager result={lookup.result} loading={lookup.loading} onPage={lookup.setPage} /> : null}
            {selected ? <p className="sub" role="status">Pessoa selecionada: <strong>{selected.nome}</strong></p> : null}
          </div>

          <div className="modal-foot">
            <DsButton variant="secondary" onClick={onClose} disabled={sending}>
              Cancelar
            </DsButton>
            <DsButton
              type="submit"
              disabled={!selected || sending}
              loading={sending}
            >
              {sending ? "Adicionando…" : "Adicionar à célula"}
            </DsButton>
          </div>
        </form>
      )}
    </DsDialog>
  );
}
