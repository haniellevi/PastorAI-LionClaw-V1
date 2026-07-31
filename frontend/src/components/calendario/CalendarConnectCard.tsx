"use client";

/**
 * Card "Conexão com o Google Agenda" — módulo de Eventos, Fase 1.
 *
 * Admin-only (retorna null para os demais). Mostra o estado da conexão, inicia
 * o OAuth (redireciona ao Google), deixa o admin escolher qual agenda usar e
 * permite desconectar.
 *
 * OAUTH-CALENDAR-V1 — o consentimento tem DOIS tempos. O `/connect` devolve um
 * `flowSecret` que guardamos em `sessionStorage` (particionado por ORIGEM: um
 * host irmão sob o mesmo domínio não lê nem grava). O callback público volta em
 * `#integracoes/callback/ready` ou `.../cancelled`; só `ready` chama o `finish`,
 * que é quem de fato conclui a conexão.
 *
 * `cancelled` e o 202 do `finish` são estados RECUPERÁVEIS: mensagem + botão
 * "Tentar novamente". Sem spinner infinito, sem polling, sem repetir o `finish`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  SessionExpiredError,
  canManageCalendar,
  disconnectCalendar,
  fetchCalendarList,
  fetchCalendarStatus,
  fetchConnectUrl,
  finishConnection,
  importEvents,
  selectCalendar,
  type CalendarOption,
  type ImportResult,
} from "@/lib/calendar-api";
import { Icon } from "@/lib/icons";
import { useHashRoute } from "@/lib/use-hash-route";

/** Marcadores de retorno. O shell divide a rota no PRIMEIRO "/", então a base
 *  continua sendo `integracoes` e o sufixo sobrevive. */
const ROUTE_BASE = "integracoes";
const ROUTE_READY = "integracoes/callback/ready";
const ROUTE_CANCELLED = "integracoes/callback/cancelled";

const FLOW_KEY = "gcal_flow";

const MSG_CANCELLED = "A conexão com o Google foi cancelada.";
const MSG_INCOMPLETE = "A conexão com o Google não foi concluída. Tente novamente.";

function readFlowSecret(): string | null {
  try {
    return window.sessionStorage.getItem(FLOW_KEY);
  } catch {
    return null; // storage indisponível: o fluxo falha fechado
  }
}

function writeFlowSecret(value: string | null): void {
  try {
    if (value) window.sessionStorage.setItem(FLOW_KEY, value);
    else window.sessionStorage.removeItem(FLOW_KEY);
  } catch {
    /* storage indisponível */
  }
}

interface CalendarConnectCardProps {
  /** EVT-6 PR6.4: chamado após importar do Google (a agenda recarrega a lista). */
  onImported?: (result: ImportResult) => void;
}

export function CalendarConnectCard({ onImported }: CalendarConnectCardProps) {
  const { user, token, expireSession } = useAuth();
  const isAdmin = user ? canManageCalendar(user.roles) : false;
  const [route, navigate] = useHashRoute();

  const [connected, setConnected] = useState(false);
  const [calendarId, setCalendarId] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<CalendarOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Estado recuperável do retorno do Google (cancelado / não concluído). */
  const [recoverable, setRecoverable] = useState<string | null>(null);
  /** Guarda contra o duplo-invoke do StrictMode: o `finish` é de uso único. */
  const handledRef = useRef(false);

  const onErr = useCallback(
    (e: unknown) => {
      if (e instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(e instanceof ApiError ? e.message : "Não foi possível falar com a agenda.");
    },
    [expireSession],
  );

  const loadStatus = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const s = await fetchCalendarStatus(token);
      setConnected(s.connected);
      setCalendarId(s.calendarId);
      if (s.connected) {
        try {
          setCalendars(await fetchCalendarList(token));
        } catch {
          /* a lista é best-effort: a conexão segue válida sem ela */
        }
      }
    } catch (e) {
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, onErr]);

  useEffect(() => {
    if (isAdmin) void loadStatus();
    else setLoading(false);
  }, [isAdmin, loadStatus]);

  // Retorno do Google. Roda UMA vez por montagem; nunca faz polling.
  useEffect(() => {
    if (!isAdmin || !token) return;
    if (route !== ROUTE_READY && route !== ROUTE_CANCELLED) return;
    if (handledRef.current) return;
    handledRef.current = true;

    if (route === ROUTE_CANCELLED) {
      setRecoverable(MSG_CANCELLED);
      return;
    }

    const flowSecret = readFlowSecret();
    if (!flowSecret) {
      setRecoverable(MSG_INCOMPLETE);
      return;
    }

    void (async () => {
      try {
        const result = await finishConnection(token, flowSecret);
        if (result.status === "conectado") {
          writeFlowSecret(null);
          navigate(ROUTE_BASE);
          await loadStatus();
          return;
        }
        // 202: o callback ainda não estacionou o code. NÃO consome o fluxo e
        // NÃO repete a chamada — o usuário decide pelo CTA.
        setRecoverable(MSG_INCOMPLETE);
      } catch (e) {
        writeFlowSecret(null);
        onErr(e);
        setRecoverable(MSG_INCOMPLETE);
      }
    })();
  }, [isAdmin, token, route, navigate, loadStatus, onErr]);

  const connect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const { authUrl, flowSecret } = await fetchConnectUrl(token);
      // Grava ANTES de sair da página: é a única chance.
      writeFlowSecret(flowSecret);
      window.location.href = authUrl; // redireciona ao consentimento do Google
    } catch (e) {
      onErr(e);
      setBusy(false);
    }
  }, [token, onErr]);

  /** CTA de recuperação: descarta o fluxo velho e começa um NOVO do zero. */
  const retry = useCallback(async () => {
    writeFlowSecret(null);
    setRecoverable(null);
    handledRef.current = false;
    navigate(ROUTE_BASE);
    await connect();
  }, [navigate, connect]);

  const pick = useCallback(
    async (id: string) => {
      if (!token || !id) return;
      setBusy(true);
      setError(null);
      try {
        const s = await selectCalendar(token, id);
        setCalendarId(s.calendarId);
      } catch (e) {
        onErr(e);
      } finally {
        setBusy(false);
      }
    },
    [token, onErr],
  );

  const runImport = useCallback(async () => {
    if (!token) return;
    setImporting(true);
    setError(null);
    try {
      const result = await importEvents(token);
      onImported?.(result);
    } catch (e) {
      onErr(e);
    } finally {
      setImporting(false);
    }
  }, [token, onErr, onImported]);

  const disconnect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectCalendar(token);
      setConnected(false);
      setCalendarId(null);
      setCalendars([]);
    } catch (e) {
      onErr(e);
    } finally {
      setBusy(false);
    }
  }, [token, onErr]);

  if (!isAdmin) return null;
  // O estado recuperável precisa aparecer mesmo antes de o status carregar.
  if (loading && !recoverable) return null;

  return (
    <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
      <div className="panel-title">
        <Icon name="calendar" /> Conexão com o Google Agenda
      </div>

      {error ? (
        <p className="sub" role="alert" style={{ color: "var(--danger)", marginTop: "var(--s2)" }}>
          {error}
        </p>
      ) : null}

      {recoverable ? (
        <div style={{ marginTop: "var(--s2)" }}>
          <p className="sub" role="status" style={{ color: "var(--muted)" }}>
            {recoverable}
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void retry()}
            disabled={busy}
            style={{ marginTop: "var(--s3)" }}
          >
            <Icon name="calendar" />
            <span>{busy ? "Abrindo o Google…" : "Tentar novamente"}</span>
          </button>
        </div>
      ) : !connected ? (
        <>
          <p className="sub" style={{ color: "var(--muted)", margin: "var(--s2) 0 var(--s3)" }}>
            Conecte a agenda do Google da igreja para sincronizar os eventos.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void connect()}
            disabled={busy}
          >
            <Icon name="calendar" />
            <span>{busy ? "Abrindo o Google…" : "Conectar Google Agenda"}</span>
          </button>
        </>
      ) : (
        <>
          <div className="conn-row" style={{ marginTop: "var(--s2)" }}>
            <span style={{ color: "var(--muted)" }}>Agenda sincronizada</span>
            <span className="pill accent">{calendarId ?? "selecione abaixo"}</span>
          </div>

          {calendars.length > 0 ? (
            <label style={{ display: "block", marginTop: "var(--s3)" }}>
              <span className="sub" style={{ color: "var(--muted)" }}>Escolha a agenda</span>
              <select
                className="input"
                value={calendarId ?? ""}
                onChange={(e) => void pick(e.target.value)}
                disabled={busy}
                style={{ display: "block", marginTop: "var(--s1)", width: "100%" }}
              >
                <option value="" disabled>
                  Selecione…
                </option>
                {calendars.map((c) => (
                  <option key={c.id} value={c.id}>
                    {(c.summary ?? c.id) + (c.primary ? " (principal)" : "")}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {/* PR212-CORRECTIVE-8: flexWrap comprovado por medição — em 320px o
              min-content do par (a palavra "Desconectar" não quebra) passa
              21,9px da borda do card mesmo sem o nowrap global do .btn. */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: "var(--s4)" }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void runImport()}
              disabled={busy || importing}
            >
              <Icon name="download" />
              <span>{importing ? "Importando…" : "Importar eventos do Google"}</span>
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => void disconnect()}
              disabled={busy || importing}
            >
              <Icon name="logout" />
              <span>Desconectar</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
