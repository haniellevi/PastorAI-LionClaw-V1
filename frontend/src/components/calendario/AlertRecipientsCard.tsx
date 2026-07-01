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
    <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
      <div className="panel-title">
        <Icon name="bell" /> Destinatários dos avisos
      </div>
      <p className="sub" style={{ color: "var(--muted)", margin: "var(--s2) 0 var(--s3)" }}>
        Receberá avisos internos da Agenda por WhatsApp.
      </p>

      {error ? (
        <p className="sub" style={{ color: "var(--danger)", marginBottom: "var(--s2)" }}>
          {error}
        </p>
      ) : null}

      {recipients.length > 0 ? (
        <ul style={{ listStyle: "none", padding: 0, margin: "0 0 var(--s3)" }}>
          {recipients.map((r) => (
            <li
              key={r.id}
              className="conn-row"
              style={{ gap: 8, padding: "var(--s2) 0", borderBottom: "1px solid var(--border)" }}
            >
              <span style={{ flex: 1, opacity: r.ativo ? 1 : 0.55 }}>
                {r.nome} · {r.telefone}
                {r.ativo ? null : <span className="pill" style={{ marginLeft: 8 }}>inativo</span>}
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => void toggle(r)}
                disabled={busyId === r.id}
              >
                {r.ativo ? "Desativar" : "Ativar"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => void remove(r)}
                disabled={busyId === r.id}
                aria-label={`Remover ${r.nome}`}
              >
                <Icon name="trash" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
          Nenhum destinatário configurado. Sem destinatário, a Agenda não envia avisos.
        </p>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          className="input"
          placeholder="Nome"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          style={{ flex: "1 1 140px" }}
        />
        <input
          className="input"
          placeholder="Telefone (WhatsApp)"
          value={telefone}
          onChange={(e) => setTelefone(e.target.value)}
          inputMode="tel"
          style={{ flex: "1 1 160px" }}
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void add()}
          disabled={adding || !nome.trim() || !telefone.trim()}
        >
          <Icon name="plus" />
          <span>{adding ? "Adicionando…" : "Adicionar"}</span>
        </button>
      </div>
    </div>
  );
}
