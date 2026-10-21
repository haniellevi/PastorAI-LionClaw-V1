"use client";

import { useEffect, useState, type MouseEvent } from "react";
import { DsButton } from "@/components/ds/Button";
import { getDashboard, type CentralDashboard } from "@/lib/cell-central-api";
import { Icon } from "@/lib/icons";

/** Read-only composition of the Central's authoritative counters. */
export function CentralPendingContext({ token, onNavigate, onSessionError }: {
  token: string;
  onNavigate: (target: string) => void;
  onSessionError: (error: unknown) => unknown;
}) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    token: string; attempt: number; data: CentralDashboard | null;
  } | null>(null);
  useEffect(() => {
    let active = true;
    void getDashboard(token, true).then(
      (data) => { if (active) setResult({ token, attempt, data }); },
      (error: unknown) => {
        if (!active) return;
        onSessionError(error);
        setResult({ token, attempt, data: null });
      },
    );
    return () => { active = false; };
  }, [token, attempt, onSessionError]);

  const current = result?.token === token && result.attempt === attempt ? result : null;
  const data = current?.data;
  const empty = data && data.relatorios_pendentes === 0 &&
    data.solicitacoes_aguardando === 0 && data.celulas_com_alerta === 0;
  function navigate(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate("central-celula");
  }
  return (
    <section className="dh-panel" aria-label="Pendências da Central" aria-busy={!current}>
      <header className="dh-panel-head">
        <span className="dh-panel-symbol" aria-hidden="true"><Icon name="central-celula" /></span>
        <h3 className="dh-panel-title">Pendências da Central</h3>
      </header>
      <div className="dh-context-body">
        {!current ? <p role="status">Carregando pendências da Central…</p> : !data ? (
          <div>
            <p role="status">Pendências da Central indisponíveis agora.</p>
            <DsButton variant="secondary" onClick={() => setAttempt(value => value + 1)}>Tentar novamente</DsButton>
          </div>
        ) : empty ? <p className="dh-context-empty">Nenhuma pendência da Central agora.</p> : (
          <ul>
            <li>{data.relatorios_pendentes} {data.relatorios_pendentes === 1 ? "relatório pendente" : "relatórios pendentes"}</li>
            <li>{data.solicitacoes_aguardando} {data.solicitacoes_aguardando === 1 ? "solicitação aguardando" : "solicitações aguardando"}</li>
            <li>{data.celulas_com_alerta} {data.celulas_com_alerta === 1 ? "célula com alerta" : "células com alerta"}</li>
          </ul>
        )}
        <a className="dh-shortcut" href="#central-celula" onClick={navigate}>Abrir Central de Células</a>
      </div>
    </section>
  );
}
