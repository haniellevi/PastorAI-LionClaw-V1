"use client";

import { useEffect, useState } from "react";
import { DsButton } from "@/components/ds/Button";
import { baixarAlert } from "@/lib/cells-api";
import { getMyCellAlerts, type MyCellAlert } from "@/lib/cell-alerts-api";
import { Icon } from "@/lib/icons";

/**
 * RF-26: alertas em aberto das células que o usuário lidera diretamente.
 * O servidor decide quem vê (líder direto) e quem baixa (mesma regra).
 */
export function LeaderAlertsContext({
  token,
  onSessionError,
}: {
  token: string;
  onSessionError: (error: unknown) => unknown;
}) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    token: string;
    attempt: number;
    data: MyCellAlert[] | null;
  } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getMyCellAlerts(token).then(
      (data) => {
        if (active) setResult({ token, attempt, data });
      },
      (error: unknown) => {
        if (!active) return;
        onSessionError(error);
        setResult({ token, attempt, data: null });
      },
    );
    return () => {
      active = false;
    };
  }, [token, attempt, onSessionError]);

  const current = result?.token === token && result.attempt === attempt ? result : null;
  const data = current?.data;

  async function tratar(alert: MyCellAlert) {
    if (busy) return;
    setBusy(alert.id);
    setFailed(null);
    try {
      await baixarAlert(token, alert.celulaId, alert.id);
      setResult((prev) =>
        prev?.data ? { ...prev, data: prev.data.filter((a) => a.id !== alert.id) } : prev,
      );
    } catch (error: unknown) {
      onSessionError(error);
      setFailed("Não foi possível tratar o alerta.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="dh-panel" aria-label="Alertas da sua célula" aria-busy={!current}>
      <header className="dh-panel-head">
        <span className="dh-panel-symbol" aria-hidden="true">
          <Icon name="alert" />
        </span>
        <h3 className="dh-panel-title">Alertas da sua célula</h3>
      </header>
      <div className="dh-context-body">
        {!current ? (
          <p role="status">Carregando alertas…</p>
        ) : !data ? (
          <div>
            <p role="status">Alertas indisponíveis agora.</p>
            <DsButton variant="secondary" onClick={() => setAttempt((value) => value + 1)}>
              Tentar novamente
            </DsButton>
          </div>
        ) : data.length === 0 ? (
          <p className="dh-context-empty">Nenhum alerta em aberto.</p>
        ) : (
          <ul>
            {data.map((alert) => (
              <li className="list-row" key={alert.id}>
                <div className="ops-row-main">
                  <div className="nm">{alert.gatilho ?? "Alerta"}</div>
                  <div className="sub">
                    {alert.celulaNome}
                    {alert.acaoEsperada ? ` · ${alert.acaoEsperada}` : ""}
                  </div>
                </div>
                <DsButton
                  variant="secondary"
                  disabled={busy === alert.id}
                  onClick={() => void tratar(alert)}
                >
                  {busy === alert.id ? "…" : "Tratar"}
                </DsButton>
              </li>
            ))}
          </ul>
        )}
        {failed ? <p role="alert">{failed}</p> : null}
      </div>
    </section>
  );
}
