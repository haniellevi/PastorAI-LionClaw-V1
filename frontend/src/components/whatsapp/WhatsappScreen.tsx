"use client";

/**
 * Tela #whatsapp — Conexão do número oficial (US-05/US-06/US-07, delta-005).
 *
 * Área RESTRITA ao papel admin (telas de Configuração). Não-admin que chegue por
 * deep-link vê o bloqueio de acesso — embora o AppShell já redirecione telas
 * ADMIN_ONLY.
 *
 * Exibe o status (connected/disconnected/reconnecting) e o qr-connect consumindo
 * api-whatsapp-connection. Conectar/reconectar troca o status sem recarregar a
 * página (polling). Quando o QR expira ele NÃO é regenerado sozinho — o admin
 * clica em "Gerar novo QR" (regenerar sozinho invalidaria o QR que ele está
 * tentando ler). Como alternativa ao QR, o admin pode informar o número para a
 * Evolution emitir um código numérico (pairingCode). Número já conectado por
 * outra instância é sinalizado (RF-07).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import {
  ApiError,
  ConnectionConflictError,
  SessionExpiredError,
  canManageWhatsapp,
  connectWhatsapp,
  disconnectWhatsapp,
  fetchConnection,
  type ConnectionInfo,
  type ConnectionStatus,
} from "@/lib/whatsapp-api";

const POLL_MS = 6_000;
const QR_TTL_MS = 45_000;

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const STATUS_META: Record<
  ConnectionStatus,
  { tone: PillTone; label: string; dot: string; title: string }
> = {
  online: { tone: "ok", label: "Online", dot: "var(--ok)", title: "Número conectado" },
  reconectando: {
    tone: "warn",
    label: "Reconectando",
    dot: "var(--warn)",
    title: "Reconectando o número",
  },
  offline: {
    tone: "danger",
    label: "Offline",
    dot: "var(--danger)",
    title: "Número desconectado",
  },
};

function formatSync(iso: string | null): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  return new Date(ts).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function WhatsappScreen() {
  const { user, token, expireSession } = useAuth();

  const [info, setInfo] = useState<ConnectionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [qr, setQr] = useState<string | null>(null);
  const [qrExpired, setQrExpired] = useState(false);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [numeroInput, setNumeroInput] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  const allowed = user ? canManageWhatsapp(user.roles) : false;
  const status: ConnectionStatus = info?.status ?? "offline";
  const meta = STATUS_META[status];

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  // ---- carga + polling de status -----------------------------------------
  const load = useCallback(
    async (mode: "initial" | "poll" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      if (mode !== "poll") setError(null);
      try {
        const data = await fetchConnection(token);
        setInfo(data);
        setLoaded(true);
        // Pareou com sucesso: limpa o QR/código e avisa.
        if (data.status === "online") {
          setQr((prev) => {
            if (prev) flashToast({ kind: "ok", text: "Número conectado com sucesso." });
            return null;
          });
          setQrExpired(false);
          setPairingCode(null);
          setNotice(null);
        }
      } catch (err) {
        if (handleSessionError(err)) return;
        if (mode !== "poll") {
          setError(
            err instanceof ApiError
              ? err.message
              : "Não foi possível carregar a conexão do WhatsApp.",
          );
        }
      } finally {
        if (mode === "initial") setLoading(false);
      }
    },
    [token, handleSessionError, flashToast],
  );

  useEffect(() => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    void load("initial");
  }, [allowed, load]);

  // Enquanto não estiver online, mantém o status atualizado sem reload.
  useEffect(() => {
    if (!allowed) return;
    if (status === "online") return;
    const id = window.setInterval(() => void load("poll"), POLL_MS);
    return () => window.clearInterval(id);
  }, [allowed, status, load]);

  // ---- conectar / reconectar ---------------------------------------------
  // Caminho QR. Nunca envia número: "Gerar novo QR"/"Reparear" usam reconnect
  // (restart reseta uma sessão presa em "connecting"); connect é só o 1º pareamento.
  const doConnect = useCallback(
    async (action: "connect" | "reconnect") => {
      if (!token) return;
      setBusy(true);
      setConflict(null);
      setNotice(null);
      try {
        const res = await connectWhatsapp(token, action);
        setInfo((prev) => ({
          numero: prev?.numero ?? null,
          status: res.status,
          ultimaSync: new Date().toISOString(),
        }));
        setQr(res.qr);
        setPairingCode(null); // caminho QR nunca produz código
        setQrExpired(false);
        if (res.qr) {
          setNotice("Leia o QR code no app do WhatsApp do número oficial da igreja.");
        }
        flashToast({
          kind: "ok",
          text: action === "connect" ? "Conexão iniciada." : "Reconexão iniciada.",
        });
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof ConnectionConflictError) {
          setConflict(err.message);
          flashToast({ kind: "err", text: err.message });
          return;
        }
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível atualizar a conexão.",
        });
      } finally {
        setBusy(false);
      }
    },
    [token, handleSessionError, flashToast],
  );

  // Caminho explícito de código: pede o pairingCode por número. O backend reseta
  // a sessão antes (senão o Evolution ignora o número e devolve só o QR). Se
  // mesmo assim não vier código, não fingimos sucesso — avisamos e oferecemos o QR.
  const doGenerateCode = useCallback(
    async (numero: string) => {
      if (!token || numero.length < 10) return;
      setBusy(true);
      setConflict(null);
      setNotice(null);
      try {
        const res = await connectWhatsapp(token, "reconnect", numero);
        setInfo((prev) => ({
          numero: prev?.numero ?? null,
          status: res.status,
          ultimaSync: new Date().toISOString(),
        }));
        setQrExpired(false);
        if (res.pairingCode) {
          setPairingCode(res.pairingCode);
          setQr(null);
          setNotice(
            "Código gerado. No WhatsApp do número oficial: Aparelhos conectados → Conectar com número de telefone.",
          );
          flashToast({ kind: "ok", text: "Código de pareamento gerado." });
        } else {
          // Evolution não emitiu o código (sessão em pareamento). Sem fingir sucesso.
          setPairingCode(null);
          setQr(res.qr);
          setNotice(
            "Não foi possível gerar o código agora (a sessão estava em pareamento). Tente de novo ou use o QR code.",
          );
          flashToast({ kind: "err", text: "Evolution não retornou o código. Tente de novo ou use o QR." });
        }
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof ConnectionConflictError) {
          setConflict(err.message);
          flashToast({ kind: "err", text: err.message });
          return;
        }
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível gerar o código.",
        });
      } finally {
        setBusy(false);
      }
    },
    [token, handleSessionError, flashToast],
  );

  // ---- desconectar (logout do aparelho) ----------------------------------
  const doDisconnect = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setConflict(null);
    setNotice(null);
    try {
      const res = await disconnectWhatsapp(token);
      setInfo({ numero: null, status: res.status, ultimaSync: new Date().toISOString() });
      setQr(null);
      setQrExpired(false);
      setPairingCode(null);
      setConfirmDisconnect(false);
      flashToast({ kind: "ok", text: "Número desconectado." });
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível desconectar o número.",
      });
    } finally {
      setBusy(false);
    }
  }, [token, handleSessionError, flashToast]);

  // ---- expiração do QR (sem regenerar sozinho) ---------------------------
  // O QR expira no servidor após alguns segundos. Ao expirar, apenas marcamos
  // como expirado e pedimos ação explícita do admin — regenerar sozinho
  // invalidaria o QR que ele está justamente tentando ler no aparelho.
  useEffect(() => {
    if (!qr || qrExpired || status === "online") return;
    const id = window.setTimeout(() => {
      setQrExpired(true);
      setNotice("QR code expirado. Gere um novo para tentar novamente.");
    }, QR_TTL_MS);
    return () => window.clearTimeout(id);
  }, [qr, qrExpired, status]);

  // ---- bloqueio de acesso (admin only) -----------------------------------
  if (!allowed) {
    return (
      <div className="screen" key="whatsapp-denied">
        <div className="card">
          <div className="access-denied">
            <Icon name="lock" className="access-ic" />
            <h3>Acesso restrito</h3>
            <p>
              A conexão do WhatsApp é configurada apenas pelo Administrador da igreja.
              Fale com a liderança se precisar de acesso.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const showSkeleton = loading && !loaded;
  const isOnline = status === "online";
  const primaryAction: "connect" | "reconnect" = info?.numero ? "reconnect" : "connect";

  return (
    <div className="screen" key="whatsapp">
      <div className="screen-head">
        <div className="actions">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            <Icon name="refresh" />
            <span>Atualizar</span>
          </button>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      {conflict ? (
        <div className="degraded-banner" role="alert" style={{ borderRadius: "var(--r-md)", marginBottom: "var(--s3)" }}>
          <Icon name="alert" />
          <span>{conflict}</span>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="conn-grid">
          <div className="card card-pad">
            <div className="sk-line sk-md" />
            <div className="sk-line sk-sm" />
            <div className="sk-line sk-sm" />
          </div>
          <div className="card card-pad">
            <div className="qr idle" />
          </div>
        </div>
      ) : (
        <div className="conn-grid">
          {/* Cartão de status da conexão */}
          <div className="card card-pad">
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "var(--s4)" }}>
              <span className="conn-status-dot" style={{ background: meta.dot }} />
              <div>
                <div style={{ fontWeight: 600 }}>{meta.title}</div>
                <div className="sub mono" style={{ color: "var(--muted)" }}>
                  {info?.numero ?? "Nenhum número pareado"}
                </div>
              </div>
              <span style={{ marginLeft: "auto" }}>
                <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
              </span>
            </div>

            <div className="conn-row">
              <span style={{ color: "var(--muted)" }}>Última sincronização</span>
              <span className="mono num">{formatSync(info?.ultimaSync ?? null)}</span>
            </div>
            <div className="conn-row">
              <span style={{ color: "var(--muted)" }}>Privacidade pastoral</span>
              <span className="pill accent">Só nº oficial registrado</span>
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: "var(--s4)" }}>
              {isOnline ? (
                <>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void doConnect("reconnect")}
                    disabled={busy}
                  >
                    {busy ? "Reconectando…" : "Reparear aparelho"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => setConfirmDisconnect(true)}
                    disabled={busy}
                  >
                    <Icon name="logout" />
                    <span>Desconectar</span>
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => void doConnect(primaryAction)}
                  disabled={busy}
                >
                  <Icon name="whatsapp" />
                  <span>
                    {busy
                      ? "Conectando…"
                      : primaryAction === "reconnect"
                        ? "Reconectar"
                        : "Conectar (ler QR code)"}
                  </span>
                </button>
              )}
            </div>

            {confirmDisconnect ? (
              <div
                className="degraded-banner"
                role="alertdialog"
                aria-label="Confirmar desconexão do WhatsApp"
                style={{
                  borderRadius: "var(--r-md)",
                  marginTop: "var(--s3)",
                  flexWrap: "wrap",
                }}
              >
                <Icon name="alert" />
                <span>
                  Desconectar o número oficial? A IA para de atender no WhatsApp até
                  você parear um número novamente.
                </span>
                <span style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={() => void doDisconnect()}
                    disabled={busy}
                  >
                    {busy ? "Desconectando…" : "Confirmar desconexão"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setConfirmDisconnect(false)}
                    disabled={busy}
                  >
                    Cancelar
                  </button>
                </span>
              </div>
            ) : null}
          </div>

          {/* qr-connect */}
          <div className="card card-pad" style={{ textAlign: "center" }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              {isOnline ? "Conexão ativa" : "Parear número"}
            </div>
            <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s4)" }}>
              {isOnline
                ? "O número já está pareado. Para trocar de aparelho, reconecte e leia um novo QR code."
                : "Abra o WhatsApp do número oficial → Aparelhos conectados → Conectar um aparelho e leia o código."}
            </p>

            {!isOnline && qr && !qrExpired ? (
              /* eslint-disable-next-line @next/next/no-img-element -- QR é data URI dinâmico; next/image não se aplica */
              <img
                className="qr"
                src={qr.startsWith("data:") ? qr : `data:image/png;base64,${qr}`}
                alt="QR code de conexão — leia no WhatsApp do número oficial"
                style={{ background: "#fff", objectFit: "contain" }}
              />
            ) : (
              <div
                className={`qr${isOnline || !qr || qrExpired ? " idle" : ""}`}
                role="img"
                aria-label={isOnline ? "Conexão pareada" : "QR code indisponível"}
              />
            )}

            <p className="sub mono" style={{ color: "var(--faint)", marginTop: "var(--s3)" }}>
              {isOnline
                ? "Pareado"
                : qrExpired
                  ? "QR expirado"
                  : qr
                    ? "Aguardando leitura"
                    : pairingCode
                      ? "Aguardando código"
                      : status === "reconectando"
                        ? "Reconectando…"
                        : "Clique em Conectar para gerar o QR"}
            </p>

            {!isOnline && qrExpired ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void doConnect("reconnect")}
                disabled={busy}
                style={{ marginTop: "var(--s3)" }}
              >
                <Icon name="refresh" />
                <span>{busy ? "Gerando…" : "Gerar novo QR"}</span>
              </button>
            ) : null}

            {!isOnline && pairingCode ? (
              <div style={{ marginTop: "var(--s3)" }}>
                <div className="sub" style={{ color: "var(--muted)" }}>
                  Código de pareamento
                </div>
                <div
                  className="mono"
                  style={{ fontSize: 22, fontWeight: 700, letterSpacing: 2 }}
                >
                  {pairingCode}
                </div>
                <p className="sub" style={{ color: "var(--muted)", marginTop: 4 }}>
                  No WhatsApp do número oficial: Aparelhos conectados → Conectar com
                  número de telefone.
                </p>
              </div>
            ) : null}

            {notice && !isOnline ? (
              <p className="sub" style={{ marginTop: "var(--s2)", color: "var(--accent)" }}>
                {notice}
              </p>
            ) : null}

            {!isOnline ? (
              <div className="field" style={{ marginTop: "var(--s4)", textAlign: "left" }}>
                <label htmlFor="wa-numero">
                  Não consegue ler o QR? Gere um código pelo número
                </label>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    id="wa-numero"
                    inputMode="numeric"
                    placeholder="Ex.: 558999771896"
                    value={numeroInput}
                    onChange={(e) => setNumeroInput(e.target.value.replace(/\D/g, ""))}
                    disabled={busy}
                    style={{ flex: 1 }}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void doGenerateCode(numeroInput)}
                    disabled={busy || numeroInput.length < 10}
                  >
                    {busy ? "Gerando…" : "Gerar código"}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
