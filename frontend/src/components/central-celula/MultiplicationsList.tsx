"use client";

/**
 * US-19 — Multiplicações. Separa pendentes (solicitações tipo `multiplicacao`
 * aguardando; decididas na aba Solicitações) das registradas (já aplicadas em
 * transação após aprovação). Leitura. Estados: loading · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  getMultiplicacoesList,
  type MultiplicacoesListOut,
} from "@/lib/multiplicacoes-api";
import { formatLongDate, formatPublishedAt } from "@/components/minha-celula/format";

const EMPTY: MultiplicacoesListOut = { pendentes: [], registradas: [] };

export function MultiplicationsList({ token }: { token: string }) {
  const [data, setData] = useState<MultiplicacoesListOut>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const res = await getMultiplicacoesList(token);
        setData(res);
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar as multiplicações.");
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const showSkeleton = loading && !loaded;
  const total = data.pendentes.length + data.registradas.length;

  return (
    <section className="card" aria-label="Multiplicações">
      <div className="panel-title">
        <Icon name="enviar" /> Multiplicações
        {total ? <span className="count">· {total}</span> : null}
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="section-body">
          {Array.from({ length: 2 }).map((_, i) => (
            <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
          ))}
        </div>
      ) : total === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="enviar" />
          <p>
            <strong>Nenhuma multiplicação.</strong>
          </p>
        </div>
      ) : (
        <div className="section-body" style={{ display: "grid", gap: "var(--s4)" }}>
          <div>
            <div className="panel-title" style={{ padding: "0 0 var(--s2)" }}>
              Pendentes <span className="count">· {data.pendentes.length}</span>
            </div>
            {data.pendentes.length === 0 ? (
              <p className="muted-note">Nenhuma multiplicação aguardando aprovação.</p>
            ) : (
              data.pendentes.map((m) => (
                <div className="list-row" key={m.id}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="nm">Multiplicação solicitada</div>
                    <div className="sub">
                      {m.created_at ? formatPublishedAt(m.created_at) : "—"}
                    </div>
                  </div>
                  <StatusPill tone="warn">Aguardando</StatusPill>
                </div>
              ))
            )}
          </div>

          <div>
            <div className="panel-title" style={{ padding: "0 0 var(--s2)" }}>
              Registradas <span className="count">· {data.registradas.length}</span>
            </div>
            {data.registradas.length === 0 ? (
              <p className="muted-note">Nenhuma multiplicação registrada ainda.</p>
            ) : (
              data.registradas.map((m) => (
                <div className="list-row" key={m.id}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="nm">{m.descendencia ?? "Nova célula"}</div>
                    <div className="sub">
                      {m.data_prevista ? formatLongDate(m.data_prevista) : "Aplicada"}
                    </div>
                  </div>
                  <StatusPill tone="ok">Registrada</StatusPill>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </section>
  );
}
