"use client";

/**
 * Triagem Jev (TypeSafe) em modo sombra — status para o master.
 *
 * Somente leitura: a chave (TYPESAFE_API_KEY) e a lista de igrejas
 * (JEV_SHADOW_TRIAGE_IGREJA_IDS) ficam no ambiente do backend, porque gravar
 * segredo de plataforma no banco exige migration própria. A chave nunca chega
 * ao navegador. "Testar conexão" usa uma mensagem sintética fixa do backend e
 * respeita o guard global ALLOW_REAL_SENDS. Mudanças no .env só valem após
 * reiniciar o backend.
 */
import { useCallback, useEffect, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  type AdminJevStatus,
  type AdminJevTeste,
  fetchJevStatus,
  testJev,
} from "@/lib/admin-api";

export interface JevModalProps {
  token: string;
  onClose: () => void;
  onExpired: () => void;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

export function JevModal({ token, onClose, onExpired }: JevModalProps) {
  const [status, setStatus] = useState<AdminJevStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [teste, setTeste] = useState<AdminJevTeste | null>(null);

  const handleErr = useCallback(
    (err: unknown, fallback: string): string | null => {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return null;
      }
      return err instanceof Error ? err.message : fallback;
    },
    [onExpired],
  );

  useEffect(() => {
    let alive = true;
    fetchJevStatus(token)
      .then((s) => {
        if (!alive) return;
        setStatus(s);
        setLoaded(true);
      })
      .catch((err) => {
        if (!alive) return;
        const m = handleErr(err, "Não foi possível carregar o status do Jev.");
        if (m) {
          setError(m);
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [token, handleErr]);

  const runTest = async () => {
    setBusy(true);
    setError(null);
    setTeste(null);
    try {
      setTeste(await testJev(token));
    } catch (err) {
      const m = handleErr(err, "Não foi possível testar o Jev.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Triagem Jev"
      footer={
        loaded ? (
          <>
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Fechar
            </button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Testando…"
              disabled={!status?.configurado || !status?.enviosExternosPermitidos}
              onClick={() => void runTest()}
            >
              Testar conexão
            </Button>
          </>
        ) : undefined
      }
    >
      <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s2)" }}>
        Modo sombra: o Jev só registra probabilidades ao lado da decisão das
        regras; não muda rota, resposta, consentimento nem etapa. A chave e a
        lista de igrejas são configuradas no ambiente do backend
        (<code>TYPESAFE_API_KEY</code> e <code>JEV_SHADOW_TRIAGE_IGREJA_IDS</code>) e
        só valem após reiniciar o backend.
      </p>

      {error ? (
        <div className="error-banner" role="alert">
          <span>{error}</span>
        </div>
      ) : null}

      {!loaded ? (
        <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
          <span className="spinner" aria-hidden="true" />
          <div className="sub" style={{ marginTop: "var(--s2)" }}>
            Carregando…
          </div>
        </div>
      ) : status ? (
        <dl style={{ display: "grid", gap: "var(--s2)", margin: 0 }}>
          <div>
            <dt className="sub">Chave de API</dt>
            <dd style={{ margin: 0 }}>
              {status.configurado ? "Configurada" : "Não configurada"}
            </dd>
          </div>
          <div>
            <dt className="sub">Envios externos (ALLOW_REAL_SENDS)</dt>
            <dd style={{ margin: 0 }}>
              {status.enviosExternosPermitidos
                ? "Permitidos"
                : "Desligados — nenhuma chamada ao Jev sai do servidor"}
            </dd>
          </div>
          <div>
            <dt className="sub">Modelo</dt>
            <dd style={{ margin: 0 }}>
              {status.modelo} · timeout {status.timeoutSegundos}s
            </dd>
          </div>
          <div>
            <dt className="sub">Igrejas em modo sombra</dt>
            <dd style={{ margin: 0 }}>
              {status.igrejas.length === 0 ? (
                "Nenhuma (desligado)"
              ) : (
                <ul style={{ margin: 0, paddingLeft: "var(--s4)" }}>
                  {status.igrejas.map((i) => (
                    <li key={i.id}>{i.nome ?? `${i.id} (não encontrada)`}</li>
                  ))}
                </ul>
              )}
              {status.idsInvalidos > 0 ? (
                <div className="sub" style={{ color: "var(--danger, var(--muted))" }}>
                  {status.idsInvalidos} id(s) inválido(s) ignorado(s) na lista.
                </div>
              ) : null}
            </dd>
          </div>
        </dl>
      ) : null}

      {teste ? (
        <div
          className="error-banner"
          role="status"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent)",
            marginTop: "var(--s3)",
          }}
        >
          <span>
            Conectado ({teste.modelo}, {teste.latenciaMs} ms): intenção{" "}
            <strong>{teste.intencao}</strong>, risco pastoral {pct(teste.riscoPastoral)},
            opt-out {pct(teste.pedeOptout)}.
          </span>
        </div>
      ) : null}
    </DsDialog>
  );
}
