"use client";

/**
 * US-18 — Saúde das células. Renderiza até 10 bolinhas por célula
 * (verde/vermelho/alerta) na ordem retornada pelo backend (menos saudáveis
 * primeiro). Cálculo é on-read no servidor (cell_health_service); aqui é leitura.
 * Estados: loading (skeleton) · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { getHealth, type CellHealth } from "@/lib/cell-central-api";

const MAX_DOTS = 10;

/** verde/vermelho/alerta → classe da bolinha; demais caem no neutro. */
function dotClass(cor: string): string {
  if (cor === "verde" || cor === "vermelho" || cor === "alerta") return `hd ${cor}`;
  return "hd";
}

const STATUS_TONE: Record<string, PillTone> = {
  saudavel: "ok",
  atencao: "warn",
  critico: "danger",
};

function statusMeta(h: CellHealth): { label: string; tone: PillTone } {
  const tone = STATUS_TONE[h.status] ?? (h.vermelhos > 0 ? "danger" : h.alertas > 0 ? "warn" : "ok");
  const label =
    h.status === "critico" || h.vermelhos > 1
      ? "Crítica"
      : h.status === "atencao" || h.alertas > 0 || h.vermelhos > 0
        ? "Atenção"
        : "Saudável";
  return { label, tone };
}

export function CellHealthList({ token }: { token: string }) {
  const [cells, setCells] = useState<CellHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const res = await getHealth(token);
        setCells(res.cells);
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar a saúde das células.");
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
    <section className="card" aria-label="Saúde das células">
      <div className="panel-title">
        <Icon name="central-celula" /> Saúde das células
        {cells.length ? <span className="count">· {cells.length}</span> : null}
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
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
          ))}
        </div>
      ) : cells.length === 0 ? (
        <DsEmptyState illustration={<Icon name="check" />} title="Nenhuma célula para avaliar." />
      ) : (
        <div>
          {cells.map((h) => {
            const meta = statusMeta(h);
            const dots = h.sinais.slice(0, MAX_DOTS);
            return (
              <div className="health-row" key={h.celula_id}>
                <div style={{ minWidth: 0 }}>
                  <div className="nm">{h.celula_nome}</div>
                  <div className="health-dots" aria-label={`${dots.length} reuniões avaliadas`}>
                    {dots.map((s) => (
                      <span key={s.reuniao_id} className={dotClass(s.cor)} title={s.cor} />
                    ))}
                  </div>
                </div>
                <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
