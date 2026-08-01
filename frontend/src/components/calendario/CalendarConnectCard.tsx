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
 * `#integracoes/callback/ready` ou `.../cancelled`; o `finish` é quem de fato
 * conclui a conexão.
 *
 * OAUTH-PWA-IOS-G3 — o `sessionStorage` NÃO é pré-requisito. Numa PWA iOS
 * instalada, sair para `accounts.google.com` é navegação fora do `scope` do
 * manifest: o iOS entrega o link ao Safari e o retorno cai num jar de storage
 * separado do da PWA; e mesmo voltando para a PWA, o iOS pode tê-la encerrado
 * em segundo plano e relançado com o `sessionStorage` zerado. Por isso o card
 * faz UMA tentativa de retomada por montagem sempre que o admin não está
 * conectado — com o segredo local quando ele existe, sem segredo nenhum quando
 * não existe. Sem segredo o servidor acha o fluxo pela identidade do Bearer.
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
  /** Guarda contra o duplo-invoke do StrictMode: o marcador é lido uma vez. */
  const handledRef = useRef(false);
  /** A retomada é de uso único por montagem — é isto que impede polling. */
  const resumedRef = useRef(false);
  /** Houve um redirect ao Google nesta montagem. Só isso libera a recarga ao
   *  voltar ao primeiro plano; sem ele, alternar de aba não chama nada. */
  const startedRef = useRef(false);
  /** A rota é LIDA pela retomada, não é dependência dela: entrar em `loadStatus`
   *  faria o `navigate` de volta à base disparar um segundo ciclo de carga. */
  const routeRef = useRef(route);
  routeRef.current = route;

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

  const applyCalendars = useCallback(async () => {
    if (!token) return;
    try {
      setCalendars(await fetchCalendarList(token));
    } catch {
      /* a lista é best-effort: a conexão segue válida sem ela */
    }
  }, [token]);

  const loadStatus = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const s = await fetchCalendarStatus(token);
      setConnected(s.connected);
      setCalendarId(s.calendarId);
      if (s.connected) {
        await applyCalendars();
        return;
      }
      if (resumedRef.current) return;
      // `cancelled` é recusa explícita do usuário: nada foi estacionado e
      // retomar aqui só atrapalharia a mensagem de recuperação.
      const marker = routeRef.current;
      if (marker === ROUTE_CANCELLED) return;
      resumedRef.current = true;

      // Retomada (OAUTH-PWA-IOS-G3). Só no marcador `ready` existe um segredo
      // local que valha apresentar; fora dele isto é uma SONDAGEM — o 202
      // ("nada meu pendente") é o caso comum e não pode virar erro na tela.
      const isReturn = marker === ROUTE_READY;
      try {
        const result = await finishConnection(token, isReturn ? readFlowSecret() : null);
        if (result.status === "conectado") {
          writeFlowSecret(null);
          setConnected(true);
          setCalendarId(result.calendarId);
          navigate(ROUTE_BASE);
          await applyCalendars();
          return;
        }
        // 202: NÃO consome o fluxo e NÃO repete a chamada — o usuário decide
        // pelo CTA, e só quando ele está de fato esperando um retorno.
        if (isReturn) setRecoverable(MSG_INCOMPLETE);
      } catch (e) {
        if (!isReturn) return; // sondagem recusada: segue o fluxo normal
        writeFlowSecret(null);
        onErr(e);
        setRecoverable(MSG_INCOMPLETE);
      }
    } catch (e) {
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, applyCalendars, navigate, onErr]);

  useEffect(() => {
    if (isAdmin) void loadStatus();
    else setLoading(false);
  }, [isAdmin, loadStatus]);

  // Marcador de retorno. Só `cancelled` tem tratamento próprio; `ready` é
  // resolvido pela retomada em `loadStatus`. Roda UMA vez por montagem.
  useEffect(() => {
    if (!isAdmin) return;
    if (route !== ROUTE_CANCELLED) return;
    if (handledRef.current) return;
    handledRef.current = true;
    setRecoverable(MSG_CANCELLED);
  }, [isAdmin, route]);

  // iOS: ir ao Google NÃO desmonta a PWA — ela fica em segundo plano com o
  // botão preso em "Abrindo o Google…", e o retorno costuma cair no Safari.
  // Voltar ao primeiro plano refaz a carga (que já embute UMA retomada). Só
  // dispara depois de um redirect real; não é polling e não roda por troca de
  // aba comum.
  useEffect(() => {
    if (!isAdmin) return;
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (!startedRef.current) return;
      startedRef.current = false;
      resumedRef.current = false;
      setBusy(false);
      void loadStatus();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [isAdmin, loadStatus]);

  const connect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const { authUrl, flowSecret } = await fetchConnectUrl(token);
      // Grava ANTES de sair da página: é a única chance — e num navegador
      // comum é o que dá precisão ao `finish`. Numa PWA iOS pode não voltar.
      writeFlowSecret(flowSecret);
      startedRef.current = true;
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
