"use client";

/**
 * US-16 — Relatórios pendentes. Fila de reuniões passadas não canceladas com
 * relatorio_status='pendente', com célula, líder (derivado de celulas.lider_id)
 * e data. Leitura paginada (mostra a 1ª página). Estados: loading · empty · erro.
 */
import { useEffect, useRef, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { getPendingReports, type PendingReportItem } from "@/lib/cell-central-api";
import { formatLongDate } from "@/components/minha-celula/format";

export function PendingReportsList({
  token,
  focusOnOpen,
}: {
  token: string;
  focusOnOpen?: boolean;
}) {
  const [items, setItems] = useState<PendingReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const section = useRef<HTMLElement>(null);

  useEffect(() => {
    if (focusOnOpen) section.current?.focus();
  }, [focusOnOpen]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setItems([]);
    void getPendingReports(token)
      .then((page) => {
        if (active) setItems(page.items);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar os relatórios pendentes.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token, attempt]);

  return (
    <section className="card" aria-label="Relatórios pendentes" tabIndex={-1} ref={section}>
      <div className="panel-title">
        <Icon name="document" /> Relatórios pendentes
        {items.length ? <span className="count">· {items.length}</span> : null}
      </div>

      {error ? (
        <DsBanner
          kind="error"
          action={
            <DsButton
              variant="secondary"
              onClick={() => setAttempt((value) => value + 1)}
              disabled={loading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {error}
        </DsBanner>
      ) : null}

      {loading ? (
        <div className="section-body" aria-hidden="true">
          {Array.from({ length: 2 }).map((_, i) => (
            <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
          ))}
        </div>
      ) : error ? null : items.length === 0 ? (
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
