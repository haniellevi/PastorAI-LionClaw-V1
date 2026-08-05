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
 * origem sobrevive a isso. O storage é limpo ao concluir, receber o 409 do
 * `finish` (fluxo inutilizável) ou iniciar deliberadamente um fluxo novo. Um
 * marcador público `cancelled` e falhas 401/403/422 preservam o segredo. O
 * relógio do cliente não decide expiração: pode estar adiantado ou atrasado.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  GoogleAccountMismatchError,
  GoogleAccountReidentifiedError,
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
  type CalendarStatus,
  type FinishResult,
  type ImportResult,
} from "@/lib/calendar-api";
import { Icon } from "@/lib/icons";
import { useHashRoute } from "@/lib/use-hash-route";

/** Marcadores de retorno. O shell divide a rota no PRIMEIRO "/", então a base
 *  continua sendo `integracoes` e o sufixo sobrevive. */
const ROUTE_BASE = "integracoes";
const ROUTE_READY = "integracoes/callback/ready";
const ROUTE_CANCELLED = "integracoes/callback/cancelled";

/** Versionada e vinculada ao usuário do app. Um navegador pode trocar de conta
 *  enquanto o consentimento está pendente; sem esse vínculo, a conta seguinte
 *  poderia consumir e invalidar o segredo da anterior. */
const FLOW_KEY_PREFIX = "gcal_flow_v3";

const MSG_CANCELLED = "A conexão com o Google foi cancelada.";
const MSG_INCOMPLETE = "A conexão com o Google não foi concluída. Tente novamente.";
const MSG_PENDING = "Você autorizou no Google? Conclua a conexão para ativar a agenda.";
const MSG_UNAVAILABLE = "Os dados desta conexão não estão mais disponíveis. Comece de novo.";
const MSG_LEGACY = "Conta Google não registrada.";

/** Mesma checagem pragmática do backend — só evita a viagem inútil. */
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface StoredFlow {
  secret: string;
  /** Epoch ms vindo do servidor. O cliente nunca calcula prazo. */
  expiresAt: number;
}

function flowKey(appUserId: string): string {
  return `${FLOW_KEY_PREFIX}:${appUserId}`;
}

function clearFlow(appUserId: string): void {
  try {
    window.localStorage.removeItem(flowKey(appUserId));
  } catch {
    /* storage indisponível */
  }
}

/** Fluxo guardado e estruturalmente válido, ou null.
 *
 * `expiresAt` valida o formato retornado pelo backend, mas o relógio local NÃO
 * decide se o fluxo morreu: um celular adiantado descartaria um segredo que o
 * servidor ainda aceita. O `/finish` é a autoridade do TTL. */
function readFlow(appUserId: string): StoredFlow | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(flowKey(appUserId));
  } catch {
    return null; // storage indisponível: o fluxo falha fechado
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredFlow>;
    const { secret, expiresAt } = parsed;
    if (
      typeof secret === "string" &&
      secret &&
      typeof expiresAt === "number" &&
      Number.isFinite(expiresAt)
    ) {
      return { secret, expiresAt };
    }
  } catch {
    /* JSON corrompido cai no clear abaixo */
  }
  clearFlow(appUserId);
  return null;
}

/** Grava e confirma a leitura. Alguns navegadores aceitam a chamada mas não
 * persistem quando o armazenamento está bloqueado; sem confirmação não há
 * posse recuperável e o consentimento não pode começar. */
function writeFlow(appUserId: string, flow: StoredFlow): boolean {
  try {
    const serialized = JSON.stringify(flow);
    const key = flowKey(appUserId);
    window.localStorage.setItem(key, serialized);
    return window.localStorage.getItem(key) === serialized;
  } catch {
    return false;
  }
}

/** Só o 409 do handler prova que o fluxo morreu/foi consumido. 401/403 podem
 * acontecer antes do handler (sessão, billing, papel) e 422 antes de consultar
 * a linha; nesses casos o segredo continua necessário e válido até o TTL. */
function makesFlowUnusable(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409;
}

/** Só falhas sem resposta confiável pedem um replay imediato do MESMO segredo.
 * Erros 4xx são respostas definitivas e nunca devem ser repetidos. */
function shouldReconcileFinishFailure(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status >= 500;
}

interface CalendarConnectCardProps {
  /** EVT-6 PR6.4: chamado após importar do Google (a agenda recarrega a lista). */
  onImported?: (result: ImportResult) => void;
}

export function CalendarConnectCard({ onImported }: CalendarConnectCardProps) {
  const { user, token, expireSession } = useAuth();
  const appUserId = user?.appUserId ?? null;
  const isAdmin = user ? canManageCalendar(user.roles) : false;
  const [route, navigate] = useHashRoute();

  const [connected, setConnected] = useState(false);
  const [calendarId, setCalendarId] = useState<string | null>(null);
  /** Revisão da conexão à qual a agenda exibida pertence. */
  const [calendarConnectionVersion, setCalendarConnectionVersion] = useState<string | null>(null);
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
  /** Conta Google VERIFICADA hoje conectada. `null` = conexão legada. */
  const [googleAccountEmail, setGoogleAccountEmail] = useState<string | null>(null);
  /** Conta que o admin declara que vai conectar — vai no corpo do `/connect`. */
  const [emailInput, setEmailInput] = useState("");
  /** Formulário de conta aberto sobre uma conexão existente (trocar/registrar). */
  const [changing, setChanging] = useState(false);
  /** Quem autorizou não é quem foi declarado. Estado terminal e acionável. */
  const [mismatch, setMismatch] = useState<
    { expected: string; verified: string } | null
  >(null);
  /** Mesmo e-mail, mas outra identidade Google. A conexão anterior fica válida
   * e os controles dela precisam permanecer acessíveis para a desconexão. */
  const [reidentified, setReidentified] = useState<string | null>(null);
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

  const applyCalendars = useCallback(async (epoch: number, adoptVersion = true) => {
    if (!token) return;
    try {
      const list = await fetchCalendarList(token);
      if (epoch !== mutationEpochRef.current) return;
      setCalendars(list.calendars);
      // Listar pode ter renovado o access token e, numa conexão legada, isso
      // avança a própria revisão. Adote a que veio COM a lista: a de
      // `/calendar/status` já nasceu velha nesse caso, e a seleção seguinte
      // tomaria 409 sem troca de identidade. Backend antigo devolve `null` —
      // aí a revisão anterior continua valendo em vez de ser apagada.
      // O reload pós-importação NÃO adota: a revisão devolvida pela
      // importação é mais fresca que qualquer lista gerada antes dela.
      if (adoptVersion && list.connectionVersion) {
        setCalendarConnectionVersion(list.connectionVersion);
      }
    } catch {
      /* a lista é best-effort: a conexão segue válida sem ela */
    }
  }, [token]);

  /** Só LÊ estado. Nunca conclui fluxo — é o que separa carregar de consentir. */
  const loadStatus = useCallback(async () => {
    if (!token || !appUserId) return;
    // A posse do fluxo é local e independe da disponibilidade do endpoint de
    // status. Revele a CTA antes da rede: uma falha transitória não pode fazer
    // a PWA oferecer um fluxo novo que substituiria o consentimento válido.
    setPending(readFlow(appUserId) !== null);
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
      setGoogleAccountEmail(s.googleAccountEmail);
      setCalendarConnectionVersion(s.connectionVersion);
      if (s.connected) {
        await applyCalendars(epoch);
      } else {
        setCalendars([]);
      }
    } catch (e) {
      // Erro de leitura obsoleta também não fala: viraria alerta espúrio por
      // cima de uma conexão que deu certo.
      if (epoch !== mutationEpochRef.current) return;
      onErr(e);
    } finally {
      setLoading(false);
    }
  }, [token, appUserId, applyCalendars, onErr]);

  /** Recompõe apenas o snapshot da conexão após um finish sem sucesso.
   *
   * O finish invalida a leitura inicial para ela não sobrescrever um sucesso.
   * Se o servidor recusar o fluxo, porém, a conexão anterior continua válida;
   * uma leitura NOVA precisa restaurá-la sem apagar o erro/mismatch exibido.
   */
  const restoreStatusAfterUnsuccessfulFinish = useCallback(async (): Promise<
    CalendarStatus | null
  > => {
    if (!token) return null;
    const epoch = mutationEpochRef.current;
    try {
      const s = await fetchCalendarStatus(token);
      if (epoch !== mutationEpochRef.current) return null;
      setConnected(s.connected);
      setCalendarId(s.calendarId);
      setGoogleAccountEmail(s.googleAccountEmail);
      setCalendarConnectionVersion(s.connectionVersion);
      if (s.connected) await applyCalendars(epoch);
      else setCalendars([]);
      return s;
    } catch (e) {
      // O erro original do finish continua sendo a mensagem acionável. Só uma
      // expiração de sessão precisa furar esse best-effort silencioso.
      if (e instanceof SessionExpiredError) expireSession();
      return null;
    }
  }, [token, applyCalendars, expireSession]);

  useEffect(() => {
    if (isAdmin) void loadStatus();
    else setLoading(false);
  }, [isAdmin, loadStatus]);

  /** Conclusão. Recebe o segredo já validado — nunca null, nunca vazio. */
  const finishWith = useCallback(
    async (flow: StoredFlow) => {
      if (!token || !appUserId) return;
      // Invalida leituras de status já em voo: foram tiradas ANTES desta
      // conclusão e não podem sobrescrever o resultado dela.
      mutationEpochRef.current += 1;
      setBusy(true);
      setError(null);
      try {
        let result: FinishResult;
        try {
          result = await finishConnection(token, flow.secret);
        } catch (firstError) {
          // Uma falha de transporte/5xx não diz se o primeiro finish chegou a
          // commitar. Repita UMA vez o MESMO segredo: o servidor responde pelo
          // resultado durável deste fluxo, nunca pelo e-mail da conexão antiga.
          // 4xx e sessão expirada são definitivos e não entram aqui.
          if (
            firstError instanceof GoogleAccountMismatchError ||
            firstError instanceof GoogleAccountReidentifiedError ||
            firstError instanceof SessionExpiredError ||
            !shouldReconcileFinishFailure(firstError)
          ) {
            throw firstError;
          }
          result = await finishConnection(token, flow.secret);
        }
        if (result.status === "conectado") {
          // Avança de novo ANTES de aplicar: pega também as leituras que
          // começaram durante o `finish` e ainda não resolveram.
          mutationEpochRef.current += 1;
          const successEpoch = mutationEpochRef.current;
          clearFlow(appUserId);
          setPending(false);
          setRecoverable(null);
          setMismatch(null);
          setReidentified(null);
          setChanging(false);
          setEmailInput("");
          setConnected(true);
          setCalendarId(result.calendarId);
          setGoogleAccountEmail(result.googleAccountEmail);
          setCalendarConnectionVersion(result.connectionVersion);
          // O snapshot atual pertence à identidade anterior. Limpe antes do
          // best-effort da conta nova: se `/calendar/list` falhar, nenhuma
          // agenda antiga pode continuar selecionável sob a identidade nova.
          setCalendars([]);
          navigate(ROUTE_BASE);
          await applyCalendars(successEpoch);
          return;
        }
        // 202: callback ainda não estacionou o code OU o primeiro finish ainda
        // processa. Preserve o segredo e deixe a próxima tentativa explícita.
        setPending(readFlow(appUserId) !== null);
        setRecoverable(MSG_INCOMPLETE);
        await restoreStatusAfterUnsuccessfulFinish();
      } catch (e) {
        // Mesmo e-mail, `sub` diferente: o backend preservou a conexão atual e
        // exige desconectá-la antes. Não transforme isso em estado recuperável,
        // pois ele esconderia justamente o botão de desconectar.
        if (e instanceof GoogleAccountReidentifiedError) {
          clearFlow(appUserId);
          setPending(false);
          setRecoverable(null);
          setMismatch(null);
          setChanging(false);
          setReidentified(e.message);
          await restoreStatusAfterUnsuccessfulFinish();
          return;
        }
        // Conta divergente: terminal e acionável. O servidor não escreveu nada —
        // a conexão anterior, se havia, continua exatamente como estava.
        if (e instanceof GoogleAccountMismatchError) {
          clearFlow(appUserId);
          setPending(false);
          setRecoverable(null);
          setReidentified(null);
          setChanging(false);
          setMismatch({ expected: e.expected, verified: e.verified });
          await restoreStatusAfterUnsuccessfulFinish();
          return;
        }
        // Só 409 é terminal para o fluxo; autorização/validação pré-handler
        // preserva o segredo para nova tentativa dentro do TTL.
        if (makesFlowUnusable(e)) {
          clearFlow(appUserId);
          setPending(false);
        }
        if (!(e instanceof SessionExpiredError)) {
          await restoreStatusAfterUnsuccessfulFinish();
        }
        onErr(e);
        setRecoverable(MSG_INCOMPLETE);
      } finally {
        setBusy(false);
      }
    },
    [
      token,
      appUserId,
      navigate,
      applyCalendars,
      onErr,
      restoreStatusAfterUnsuccessfulFinish,
    ],
  );

  /** Única porta para o `finish`: relê o storage e desiste se não houver segredo
   *  bem formado. A validade temporal é decidida pelo servidor. */
  const finishFromStorage = useCallback(async () => {
    if (!appUserId) return;
    const flow = readFlow(appUserId);
    if (!flow) {
      setPending(false);
      setRecoverable(MSG_UNAVAILABLE);
      return;
    }
    await finishWith(flow);
  }, [appUserId, finishWith]);

  // Marcadores de retorno, uma vez por montagem.
  //  * `ready`     — o usuário acabou de consentir; com segredo vivo, conclui.
  //                  Sem segredo é fail-closed: nada de POST, só reinício.
  //  * `cancelled` — oferece reinício, mas preserva o fluxo guardado. O callback
  //                  é público e não carrega correlação suficiente para provar
  //                  que o marcador pertence ao fluxo atualmente no storage.
  useEffect(() => {
    if (!isAdmin || !token || !appUserId) return;
    if (route !== ROUTE_READY && route !== ROUTE_CANCELLED) return;
    if (handledRef.current) return;
    handledRef.current = true;

    if (route === ROUTE_CANCELLED) {
      setPending(false);
      setRecoverable(MSG_CANCELLED);
      return;
    }

    const flow = readFlow(appUserId);
    if (!flow) {
      setPending(false);
      setRecoverable(MSG_INCOMPLETE);
      navigate(ROUTE_BASE);
      return;
    }
    void finishWith(flow);
  }, [isAdmin, token, appUserId, route, navigate, finishWith]);

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

  /** Conta declarada, normalizada como o backend normaliza. */
  const declaredEmail = emailInput.trim().toLowerCase();
  const emailValid = EMAIL_RE.test(declaredEmail);

  const connect = useCallback(async () => {
    if (!token || !appUserId) return;
    // Fail-closed no cliente: sem conta declarada não existe contra o que o
    // backend comparar, então nem inicia.
    if (!emailValid) return;
    setBusy(true);
    setRedirecting(true);
    setError(null);
    setRecoverable(null);
    setMismatch(null);
    setReidentified(null);
    // Fluxo novo por decisão do usuário: o anterior morre aqui.
    clearFlow(appUserId);
    setPending(false);
    try {
      const { authUrl, flowSecret, expiresAt } = await fetchConnectUrl(
        token,
        declaredEmail,
      );
      // Grava ANTES de sair da página: é a única chance.
      if (!writeFlow(appUserId, { secret: flowSecret, expiresAt })) {
        setError(
          "Este navegador não permitiu guardar a conexão. Libere o armazenamento do site e tente novamente.",
        );
        setBusy(false);
        setRedirecting(false);
        return;
      }
      setPending(true);
      startedRef.current = true;
      window.location.href = authUrl; // redireciona ao consentimento do Google
    } catch (e) {
      onErr(e);
      setBusy(false);
      setRedirecting(false);
    }
  }, [token, appUserId, emailValid, declaredEmail, onErr]);

  /** Reinício: descarta o que houver e volta ao formulário de conta. */
  const restart = useCallback(() => {
    if (appUserId) clearFlow(appUserId);
    setPending(false);
    setRecoverable(null);
    setMismatch(null);
    setReidentified(null);
    setError(null);
    handledRef.current = false;
    navigate(ROUTE_BASE);
  }, [appUserId, navigate]);

  const pick = useCallback(
    async (id: string) => {
      if (!token || !id) return;
      if (!calendarConnectionVersion) {
        setError("Reconecte a agenda do Google antes de selecionar outra agenda.");
        return;
      }
      mutationEpochRef.current += 1;
      const epoch = mutationEpochRef.current;
      setBusy(true);
      setError(null);
      try {
        const s = await selectCalendar(token, id, calendarConnectionVersion);
        if (epoch !== mutationEpochRef.current) return;
        setCalendarId(s.calendarId);
        setCalendarConnectionVersion(s.connectionVersion);
      } catch (e) {
        if (epoch !== mutationEpochRef.current) return;
        if (e instanceof ApiError && e.status === 409) await loadStatus();
        if (epoch !== mutationEpochRef.current) return;
        onErr(e);
      } finally {
        setBusy(false);
      }
    },
    [token, calendarConnectionVersion, loadStatus, onErr],
  );

  const runImport = useCallback(async () => {
    if (!token) return;
    mutationEpochRef.current += 1;
    const epoch = mutationEpochRef.current;
    let importSucceeded = false;
    setImporting(true);
    setError(null);
    try {
      const result = await importEvents(token);
      importSucceeded = true;
      // Importar também renova o token e avança a revisão legada. Sem adotá-la,
      // uma seleção de agenda feita depois da importação levaria 409.
      if (result.connectionVersion && epoch === mutationEpochRef.current) {
        setCalendarConnectionVersion(result.connectionVersion);
      }
      onImported?.(result);
    } catch (e) {
      onErr(e);
    } finally {
      // A época avançou ao começar, então uma lista em voo vinda do
      // `loadStatus` já nasceu descartada. Sem este reload, o seletor ficava
      // vazio/obsoleto até o próximo status ou reload da página. Best-effort
      // e guardado pela época: se outra mutação veio depois, ele se descarta.
      // Em sucesso, a revisão da importação é a mais fresca. Em falha, porém,
      // a própria listagem pode renovar o token legado e avançar a revisão;
      // nesse caso ela precisa ser adotada para a próxima seleção não dar 409.
      await applyCalendars(epoch, !importSucceeded);
      setImporting(false);
    }
  }, [token, applyCalendars, onErr, onImported]);

  const disconnect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      mutationEpochRef.current += 1;
      await disconnectCalendar(token);
      setConnected(false);
      setCalendarId(null);
      setGoogleAccountEmail(null);
      setCalendarConnectionVersion(null);
      setChanging(false);
      setReidentified(null);
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
  if (loading && !recoverable && !pending && !connected && !mismatch && !reidentified) return null;

  /** Bloco inline reusado nos três pontos que pedem a conta declarada. */
  const accountForm = (label: string, cta: string) => (
    <>
      <label style={{ display: "block", marginTop: "var(--s3)" }}>
        <span className="sub" style={{ color: "var(--muted)" }}>{label}</span>
        <input
          className="input"
          type="email"
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
          placeholder="agenda@suaigreja.com.br"
          autoComplete="email"
          disabled={busy}
          aria-label={label}
          style={{ display: "block", marginTop: "var(--s1)", width: "100%" }}
        />
      </label>

      {googleAccountEmail && emailValid && declaredEmail !== googleAccountEmail ? (
        <p className="sub" role="status" style={{ color: "var(--warn)", marginTop: "var(--s2)" }}>
          Isto TROCA a conta conectada: de {googleAccountEmail} para {declaredEmail}.
        </p>
      ) : null}

      <button
        type="button"
        className="btn btn-primary"
        onClick={() => void connect()}
        disabled={busy || !emailValid}
        style={{ marginTop: "var(--s3)" }}
      >
        <Icon name="calendar" />
        <span>{redirecting ? "Abrindo o Google…" : cta}</span>
      </button>
    </>
  );

  // Um `cancelled` público não prova que o fluxo guardado foi cancelado. Ele é
  // preservado contra DoS, mas não oferecemos `finish` para um marcador sem
  // correlação; a única ação visível é iniciar um fluxo novo, que o substitui.
  const canFinishPending = pending && recoverable !== MSG_CANCELLED;

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

      {reidentified ? (
        <p className="sub" role="alert" style={{ color: "var(--danger)", marginTop: "var(--s2)" }}>
          {reidentified}
        </p>
      ) : null}

      {mismatch ? (
        /* Conta divergente: o servidor NÃO escreveu nada. Mostrar as duas
           contas é o que torna o erro corrigível. */
        <div style={{ marginTop: "var(--s2)" }}>
          <p className="sub" role="alert" style={{ color: "var(--danger)" }}>
            A conta que autorizou no Google não é a que você informou.
          </p>
          <p className="sub" style={{ color: "var(--muted)", marginTop: "var(--s2)" }}>
            Você informou <strong>{mismatch.expected}</strong> e quem autorizou foi{" "}
            <strong>{mismatch.verified}</strong>. Nada foi alterado — a conexão da
            igreja continua exatamente como estava.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={restart}
            disabled={busy}
            style={{ marginTop: "var(--s3)" }}
          >
            <Icon name="calendar" />
            <span>Tentar novamente</span>
          </button>
        </div>
      ) : recoverable || !connected || pending ? (
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
              Sem segredo, o caminho é declarar a conta e começar um fluxo. */}
          {canFinishPending ? (
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
                onClick={restart}
                disabled={busy}
              >
                <span>Começar de novo</span>
              </button>
            </div>
          ) : (
            accountForm(
              "Qual conta Google será conectada? Informe o e-mail exato.",
              recoverable ? "Tentar novamente" : "Conectar Google Agenda",
            )
          )}
        </>
      ) : (
        <>
          {/* Identidade primeiro: é ela que responde "de quem é esta agenda?".
              `null` = conexão legada, anterior ao binding — segue válida, mas o
              admin pode registrar a conta sem desconectar nada. */}
          <div className="conn-row" style={{ marginTop: "var(--s2)" }}>
            <span style={{ color: "var(--muted)" }}>
              {googleAccountEmail ? "Conectado como" : MSG_LEGACY}
            </span>
            {googleAccountEmail ? (
              <span className="pill accent">{googleAccountEmail}</span>
            ) : null}
          </div>

          {changing ? (
            accountForm(
              googleAccountEmail
                ? "Qual conta Google passará a valer? Informe o e-mail exato."
                : "Qual conta Google está conectada? Informe o e-mail exato.",
              googleAccountEmail ? "Trocar conta Google" : "Registrar conta Google",
            )
          ) : !reidentified ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setEmailInput(googleAccountEmail ?? "");
                setChanging(true);
              }}
              disabled={busy || importing}
              style={{ marginTop: "var(--s2)" }}
            >
              <span>
                {googleAccountEmail ? "Trocar conta Google" : "Registrar conta Google"}
              </span>
            </button>
          ) : null}

          <div className="conn-row" style={{ marginTop: "var(--s3)" }}>
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
                disabled={busy || importing}
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
