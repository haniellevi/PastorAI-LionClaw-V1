"use client";

/**
 * US-16 — Relatórios pendentes. Fila de reuniões passadas não canceladas com
 * relatorio_status='pendente', com célula, líder (derivado de celulas.lider_id)
 * e data. Leitura paginada (mostra a 1ª página). Estados: loading · empty · erro.
 */
import { useCallback, useEffect, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { getPendingReports, type PendingReportItem } from "@/lib/cell-central-api";
import { formatLongDate } from "@/components/minha-celula/format";

export function PendingReportsList({ token }: { token: string }) {
  const [items, setItems] = useState<PendingReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await getPendingReports(token);
        setItems(page.items);
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar os relatórios pendentes.");
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

  return (
    <section className="card" aria-label="Relatórios pendentes">
      <div className="panel-title">
        <Icon name="document" /> Relatórios pendentes
        {items.length ? <span className="count">· {items.length}</span> : null}
      </div>

      {error ? (
        <DsBanner
          kind="error"
          action={
            <DsButton variant="secondary" onClick={() => void load("retry")} disabled={loading}>
              Tentar novamente
            </DsButton>
          }
        >
          {error}
        </DsBanner>
      ) : null}

      {showSkeleton ? (
        <div className="section-body">
          {Array.from({ length: 2 }).map((_, i) => (
            <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <DsEmptyState illustration={<Icon name="check" />} title="Nenhum relatório pendente." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Célula</th>
              <th>Líder</th>
              <th>Reunião</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.reuniao_id}>
                <td className="nm">{r.celula_nome}</td>
                <td className="sub">{r.lider_nome}</td>
                <td className="sub">{formatLongDate(r.data)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
