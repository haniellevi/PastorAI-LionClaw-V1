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
 * página (polling). QR expirado é regenerado automaticamente com aviso; número já
 * conectado por outra instância é sinalizado (RF-07).
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
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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
        // Pareou com sucesso: limpa o QR e avisa.
        if (data.status === "online") {
          setQr((prev) => {
            if (prev) flashToast({ kind: "ok", text: "Número conectado com sucesso." });
            return null;
          });
          setQrExpired(false);
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
  const doConnect = useCallback(
    async (action: "connect" | "reconnect", auto = false) => {
      if (!token) return;
      setBusy(true);
      setConflict(null);
      if (!auto) setNotice(null);
      try {
        const res = await connectWhatsapp(token, action);
        setInfo((prev) => ({
          numero: prev?.numero ?? null,
          status: res.status,
          ultimaSync: new Date().toISOString(),
        }));
        setQr(res.qr);
        setQrExpired(false);
        if (res.qr) {
          setNotice(
            auto
              ? "QR code expirado. Geramos um novo — leia no WhatsApp do aparelho."
              : "Leia o QR code no app do WhatsApp do número oficial da igreja.",
          );
        }
        if (!auto) {
          flashToast({
            kind: "ok",
            text: action === "connect" ? "Conexão iniciada." : "Reconexão iniciada.",
          });
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
          text: err instanceof ApiError ? err.message : "Não foi possível atualizar a conexão.",
        });
      } finally {
        setBusy(false);
      }
    },
    [token, handleSessionError, flashToast],
  );

  // ---- expiração + regeneração automática do QR --------------------------
  useEffect(() => {
    if (!qr || status === "online") return;
    const id = window.setTimeout(() => {
      setQrExpired(true);
      setNotice("QR code expirado. Gerando um novo…");
      // Regenera automaticamente (reconnect mantém o número/instância).
      void doConnect(info?.numero ? "reconnect" : "connect", true);
    }, QR_TTL_MS);
    return () => window.clearTimeout(id);
  }, [qr, status, info?.numero, doConnect]);

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
                <button
                  type="button"
                  className="btn"
                  onClick={() => void doConnect("reconnect")}
                  disabled={busy}
                >
                  {busy ? "Reconectando…" : "Reparear aparelho"}
                </button>
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
                : status === "reconectando"
                  ? "Reconectando…"
                  : qrExpired
                    ? "QR expirado — gerando novo"
                    : qr
                      ? "Aguardando leitura"
                      : "Clique em Conectar para gerar o QR"}
            </p>

            {notice && !isOnline ? (
              <p className="sub" style={{ marginTop: "var(--s2)", color: "var(--accent)" }}>
                {notice}
              </p>
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
