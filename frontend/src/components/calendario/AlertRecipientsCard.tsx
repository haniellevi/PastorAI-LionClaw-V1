"use client";

/**
 * Card "Destinatários dos avisos" — Agenda, EVT-7 PR2.
 *
 * Admin-only (retorna null para os demais). Configura quem recebe os avisos
 * internos da Agenda por WhatsApp — independente de papel (ver ADR EVT-7). Só
 * CONFIGURA: nada é enviado daqui (o envio é do backend, atrás da flag). Campos
 * mínimos: nome, telefone, ativar/desativar e remover.
 */
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  SessionExpiredError,
  canManageCalendar,
  createAlertRecipient,
  deleteAlertRecipient,
  fetchAlertRecipients,
  updateAlertRecipient,
  type AlertRecipient,
} from "@/lib/calendar-api";
import { Icon } from "@/lib/icons";
import { DsButton } from "@/components/ds/Button";

export function AlertRecipientsCard() {
  const { user, token, expireSession } = useAuth();
  const isAdmin = user ? canManageCalendar(user.roles) : false;

  const [recipients, setRecipients] = useState<AlertRecipient[]>([]);
  const [loading, setLoading] = useState(true);
  const [nome, setNome] = useState("");
  const [telefone, setTelefone] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onErr = useCallback(
    (e: unknown) => {
      if (e instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(e instanceof ApiError ? e.message : "Não foi possível falar com a Agenda.");
    },
    [expireSession],
  );

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setRecipients(await fetchAlertRecipients(token));
    } catch (e) {
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, onErr]);

  useEffect(() => {
    if (isAdmin) void load();
    else setLoading(false);
  }, [isAdmin, load]);

  const add = useCallback(async () => {
    if (!token || !nome.trim() || !telefone.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const created = await createAlertRecipient(token, nome.trim(), telefone.trim());
      setRecipients((prev) => [...prev, created]);
      setNome("");
      setTelefone("");
    } catch (e) {
      onErr(e);
    } finally {
      setAdding(false);
    }
  }, [token, nome, telefone, onErr]);

  const toggle = useCallback(
    async (r: AlertRecipient) => {
      if (!token) return;
      setBusyId(r.id);
      setError(null);
      try {
        const updated = await updateAlertRecipient(token, r.id, { ativo: !r.ativo });
        setRecipients((prev) => prev.map((x) => (x.id === r.id ? updated : x)));
      } catch (e) {
        onErr(e);
      } finally {
        setBusyId(null);
      }
    },
    [token, onErr],
  );

  const remove = useCallback(
    async (r: AlertRecipient) => {
      if (!token) return;
      setBusyId(r.id);
      setError(null);
      try {
        await deleteAlertRecipient(token, r.id);
        setRecipients((prev) => prev.filter((x) => x.id !== r.id));
      } catch (e) {
        onErr(e);
      } finally {
        setBusyId(null);
      }
    },
    [token, onErr],
  );

  if (!isAdmin || loading) return null;

  return (
    <div className="card card-pad ds-mb-4">
      <div className="panel-title">
        <Icon name="bell" /> Destinatários dos avisos
      </div>
      <p className="sub ds-muted ds-m-0 ds-mt-2 ds-mb-3">
        Receberá avisos internos da Agenda por WhatsApp.
      </p>

      {error ? (
        <p className="sub ds-text-danger ds-mb-2" role="alert">
          {error}
        </p>
      ) : null}

      {recipients.length > 0 ? (
        <ul className="alert-recipient-list">
          {recipients.map((r) => (
            <li
              key={r.id}
              className="conn-row alert-recipient-row"
            >
              <span className={r.ativo ? "alert-recipient-name" : "alert-recipient-name is-inactive"}>
                {r.nome} · {r.telefone}
                {r.ativo ? null : <span className="pill alert-recipient-pill">inativo</span>}
              </span>
              <DsButton
                variant="secondary"
                onClick={() => void toggle(r)}
                disabled={busyId === r.id}
              >
                {r.ativo ? "Desativar" : "Ativar"}
              </DsButton>
              <DsButton
                variant="danger"
                onClick={() => void remove(r)}
                disabled={busyId === r.id}
                aria-label={`Remover ${r.nome}`}
              >
                <Icon name="trash" />
              </DsButton>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sub ds-muted ds-mb-3">
          Nenhum destinatário configurado. Sem destinatário, a Agenda não envia avisos.
        </p>
      )}

      <div className="ds-flex ds-gap-2 ds-wrap">
        <label className="sr-only" htmlFor="alert-recipient-nome">Nome</label>
        <input
          id="alert-recipient-nome"
          className="input alert-recipient-input"
          placeholder="Nome"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
        />
        <label className="sr-only" htmlFor="alert-recipient-telefone">Telefone (WhatsApp)</label>
        <input
          id="alert-recipient-telefone"
          className="input alert-recipient-input alert-recipient-input--tel"
          placeholder="Telefone (WhatsApp)"
          value={telefone}
          onChange={(e) => setTelefone(e.target.value)}
          inputMode="tel"
        />
        <DsButton
          onClick={() => void add()}
          disabled={adding || !nome.trim() || !telefone.trim()}
        >
          <Icon name="plus" />
          <span>{adding ? "Adicionando…" : "Adicionar"}</span>
        </DsButton>
      </div>
    </div>
  );
}
