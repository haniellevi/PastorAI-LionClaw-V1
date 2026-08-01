"use client";

/**
 * Card "Conexão com o Google Agenda" — módulo de Eventos, Fase 1.
 *
 * Admin-only (retorna null para os demais). Mostra o estado da conexão, inicia
 * o OAuth (redireciona ao Google), deixa o admin escolher qual agenda usar e
 * permite desconectar.
 *
 * OAUTH-CALENDAR-V1 — o consentimento tem DOIS tempos. O `/connect` devolve um
 * `flowSecret` e a expiração REAL do fluxo. O callback público volta em
 * `#integracoes/callback/ready` ou `.../cancelled`; o `finish` é quem de fato
 * conclui a conexão, e ele EXIGE o segredo.
 *
 * PR222-OPTIONAL-SECRET-SECURITY-FIX-1 — duas regras que não se negociam:
 *
 * 1. **Sem segredo válido, nenhum POST de `finish`.** Identidade autenticada não
 *    substitui posse: ela prova quem finaliza, nunca qual conta Google
 *    consentiu. Concluir por identidade deixava um `state` vazado virar
 *    vinculação de conta silenciosa — bastava um terceiro abrir a URL de
 *    autorização original noutro navegador, consentir com a conta dele, e o
 *    admin abrir esta tela. PKCE não barra isso: o code sai amarrado ao MESMO
 *    `code_challenge`.
 * 2. **Fora do marcador `ready`, quem conclui é o usuário.** Nem a montagem nem
 *    o `visibilitychange` chamam o `finish`; eles só revelam a CTA "Concluir
 *    conexão com o Google". O `visibilitychange` existe porque numa PWA iOS o
 *    app fica vivo em segundo plano com o botão preso em "Abrindo o Google…".
 *
 * O segredo vive no `localStorage` da PRÓPRIA origem (chave versionada), com o
 * `expiresAt` que veio do servidor. `localStorage` — e não `sessionStorage` —
 * porque a PWA iOS pode ser encerrada em segundo plano e relançada; o jar da
 * origem sobrevive a isso. O storage é limpo ao expirar, concluir, cancelar,
 * receber rejeição terminal ou iniciar deliberadamente um fluxo novo.
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

/** Versionada: o formato mudou de string crua em `sessionStorage` para objeto
 *  com prazo em `localStorage`. Chave nova evita ler lixo do formato antigo. */
const FLOW_KEY = "gcal_flow_v2";

const MSG_CANCELLED = "A conexão com o Google foi cancelada.";
const MSG_INCOMPLETE = "A conexão com o Google não foi concluída. Tente novamente.";
const MSG_PENDING = "Você autorizou no Google? Conclua a conexão para ativar a agenda.";
const MSG_EXPIRED = "O prazo desta conexão terminou. Comece de novo.";

interface StoredFlow {
  secret: string;
  /** Epoch ms vindo do servidor. O cliente nunca calcula prazo. */
  expiresAt: number;
}

function clearFlow(): void {
  try {
    window.localStorage.removeItem(FLOW_KEY);
  } catch {
    /* storage indisponível */
  }
}

/** Fluxo guardado e AINDA vivo, ou null. Qualquer coisa fora do formato — ou já
 *  vencida — é apagada na leitura: segredo sem prazo não fica para trás. */
function readFlow(): StoredFlow | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(FLOW_KEY);
  } catch {
    return null; // storage indisponível: o fluxo falha fechado
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredFlow>;
    const { secret, expiresAt } = parsed;
    if (typeof secret === "string" && secret && typeof expiresAt === "number") {
      if (expiresAt > Date.now()) return { secret, expiresAt };
    }
  } catch {
    /* JSON corrompido cai no clear abaixo */
  }
  clearFlow();
  return null;
}

function writeFlow(flow: StoredFlow): void {
  try {
    window.localStorage.setItem(FLOW_KEY, JSON.stringify(flow));
  } catch {
    /* storage indisponível */
  }
}

/** Recusa do servidor que não adianta repetir: o fluxo morreu. 5xx e falha de
 *  rede NÃO entram aqui — ali o segredo ainda vale e a CTA continua útil. */
function isTerminal(e: unknown): boolean {
  return e instanceof ApiError && e.status >= 400 && e.status < 500;
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
  /** Saímos para o Google e a página ainda não foi embora — numa PWA iOS ela
   *  nunca vai. Separado de `busy` só para o rótulo não dizer "Concluindo…". */
  const [redirecting, setRedirecting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Estado recuperável do retorno do Google (cancelado / não concluído). */
  const [recoverable, setRecoverable] = useState<string | null>(null);
  /** Há segredo de fluxo vivo nesta origem. Só isto habilita a CTA de conclusão.
   *  Começa `false` para não tocar em `window` durante o SSR. */
  const [pending, setPending] = useState(false);
  /** Guarda contra o duplo-invoke do StrictMode: o marcador é lido uma vez. */
  const handledRef = useRef(false);
  /** Houve um redirect ao Google nesta montagem. Só isso libera o destrave da UI
   *  ao voltar ao primeiro plano; sem ele, alternar de aba não faz nada. */
  const startedRef = useRef(false);
  /** Época monotônica de MUTAÇÃO do estado da conexão.
   *
   *  `loadStatus` captura a época antes do `await` e só escreve se ela ainda for
   *  a atual. Uma conclusão avança o contador DUAS vezes: ao começar (invalida
   *  leituras já em voo) e imediatamente antes de aplicar o resultado (invalida
   *  também as que começaram durante o `finish` e ainda vão resolver). Sem isso,
   *  um `GET /calendar/status` lento tirado antes da conexão volta depois dela e
   *  reescreve `connected=false` por cima do sucesso. Um booleano
   *  `finishingRef` não resolve: a resposta velha chega depois do `finally`. */
  const mutationEpochRef = useRef(0);

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

  /** Só LÊ estado. Nunca conclui fluxo — é o que separa carregar de consentir. */
  const loadStatus = useCallback(async () => {
    if (!token) return;
    // Fotografia da época ANTES do await: se uma conclusão avançar o contador
    // enquanto esta leitura está em voo, o snapshot velho não escreve nada.
    const epoch = mutationEpochRef.current;
    setLoading(true);
    setError(null);
    try {
      const s = await fetchCalendarStatus(token);
      if (epoch !== mutationEpochRef.current) return; // leitura obsoleta
      setConnected(s.connected);
      setCalendarId(s.calendarId);
      setPending(!s.connected && readFlow() !== null);
      if (s.connected) {
        clearFlow();
        setPending(false);
        await applyCalendars();
      }
    } catch (e) {
      // Erro de leitura obsoleta também não fala: viraria alerta espúrio por
      // cima de uma conexão que deu certo.
      if (epoch !== mutationEpochRef.current) return;
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, applyCalendars, onErr]);

  useEffect(() => {
    if (isAdmin) void loadStatus();
    else setLoading(false);
  }, [isAdmin, loadStatus]);

  /** Conclusão. Recebe o segredo já validado — nunca null, nunca vazio. */
  const finishWith = useCallback(
    async (secret: string) => {
      if (!token) return;
      // Invalida leituras de status já em voo: foram tiradas ANTES desta
      // conclusão e não podem sobrescrever o resultado dela.
      mutationEpochRef.current += 1;
      setBusy(true);
      setError(null);
      try {
        const result = await finishConnection(token, secret);
        if (result.status === "conectado") {
          // Avança de novo ANTES de aplicar: pega também as leituras que
          // começaram durante o `finish` e ainda não resolveram.
          mutationEpochRef.current += 1;
          clearFlow();
          setPending(false);
          setRecoverable(null);
          setConnected(true);
          setCalendarId(result.calendarId);
          navigate(ROUTE_BASE);
          await applyCalendars();
          return;
        }
        // 202: o callback ainda não estacionou o code. NÃO consome o fluxo e
        // NÃO repete a chamada — o segredo fica até o TTL e a CTA segue à mão.
        setPending(readFlow() !== null);
        setRecoverable(MSG_INCOMPLETE);
      } catch (e) {
        // Terminal (4xx): o fluxo morreu, descarta o segredo e oferece reinício.
        if (isTerminal(e)) {
          clearFlow();
          setPending(false);
        }
        onErr(e);
        setRecoverable(MSG_INCOMPLETE);
      } finally {
        setBusy(false);
      }
    },
    [token, navigate, applyCalendars, onErr],
  );

  /** Única porta para o `finish`: relê o storage e desiste se não houver segredo
   *  vivo. É isto que garante que `finishConnection` nunca recebe null. */
  const finishFromStorage = useCallback(async () => {
    const flow = readFlow();
    if (!flow) {
      setPending(false);
      setRecoverable(MSG_EXPIRED);
      return;
    }
    await finishWith(flow.secret);
  }, [finishWith]);

  // Marcadores de retorno, uma vez por montagem.
  //  * `ready`     — o usuário acabou de consentir; com segredo vivo, conclui.
  //                  Sem segredo é fail-closed: nada de POST, só reinício.
  //  * `cancelled` — recusa explícita: descarta o fluxo e oferece reinício.
  useEffect(() => {
    if (!isAdmin || !token) return;
    if (route !== ROUTE_READY && route !== ROUTE_CANCELLED) return;
    if (handledRef.current) return;
    handledRef.current = true;

    if (route === ROUTE_CANCELLED) {
      clearFlow();
      setPending(false);
      setRecoverable(MSG_CANCELLED);
      return;
    }

    const flow = readFlow();
    if (!flow) {
      setPending(false);
      setRecoverable(MSG_INCOMPLETE);
      navigate(ROUTE_BASE);
      return;
    }
    void finishWith(flow.secret);
  }, [isAdmin, token, route, navigate, finishWith]);

  // iOS: ir ao Google NÃO desmonta a PWA — ela fica em segundo plano com o botão
  // preso em "Abrindo o Google…", e o retorno costuma cair no Safari. Voltar ao
  // primeiro plano DESTRAVA a UI e revela a CTA. Não conclui nada sozinho.
  useEffect(() => {
    if (!isAdmin) return;
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (!startedRef.current) return;
      startedRef.current = false;
      setBusy(false);
      setRedirecting(false);
      void loadStatus();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [isAdmin, loadStatus]);

  const connect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setRedirecting(true);
    setError(null);
    setRecoverable(null);
    // Fluxo novo por decisão do usuário: o anterior morre aqui.
    clearFlow();
    setPending(false);
    try {
      const { authUrl, flowSecret, expiresAt } = await fetchConnectUrl(token);
      // Grava ANTES de sair da página: é a única chance.
      writeFlow({ secret: flowSecret, expiresAt });
      setPending(true);
      startedRef.current = true;
      window.location.href = authUrl; // redireciona ao consentimento do Google
    } catch (e) {
      onErr(e);
      setBusy(false);
      setRedirecting(false);
    }
  }, [token, onErr]);

  /** Reinício: descarta o que houver e começa um fluxo do zero. */
  const restart = useCallback(async () => {
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
  // Os estados de retorno precisam aparecer mesmo antes de o status carregar —
  // e `connected` vindo de uma conclusão vale mesmo com uma leitura de status
  // ainda em voo, senão o card some justo depois de conectar.
  if (loading && !recoverable && !pending && !connected) return null;

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

      {!connected ? (
        <>
          <p
            className="sub"
            role={recoverable || pending ? "status" : undefined}
            style={{ color: "var(--muted)", margin: "var(--s2) 0 var(--s3)" }}
          >
            {recoverable ??
              (pending
                ? MSG_PENDING
                : "Conecte a agenda do Google da igreja para sincronizar os eventos.")}
          </p>

          {/* Com segredo vivo, a conclusão é do usuário — nunca automática.
              Sem segredo, o único caminho é começar um fluxo novo. */}
          {pending ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void finishFromStorage()}
                disabled={busy}
              >
                <Icon name="calendar" />
                <span>
                  {redirecting
                    ? "Abrindo o Google…"
                    : busy
                      ? "Concluindo…"
                      : "Concluir conexão com o Google"}
                </span>
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => void restart()}
                disabled={busy}
              >
                <span>Começar de novo</span>
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void (recoverable ? restart() : connect())}
              disabled={busy}
            >
              <Icon name="calendar" />
              <span>
                {busy
                  ? "Abrindo o Google…"
                  : recoverable
                    ? "Tentar novamente"
                    : "Conectar Google Agenda"}
              </span>
            </button>
          )}
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
