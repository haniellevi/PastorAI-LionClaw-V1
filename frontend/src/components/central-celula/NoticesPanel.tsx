"use client";

/**
 * Aba "Avisos" da Central. Publica avisos (CentralNoticeForm, US-20) e lista os
 * avisos ativos com opção de INATIVAR (deleteNotice) — sem edição no MVP:
 * corrigir = desativar e criar novo. Avisos de célula = azul; igreja/Central =
 * vermelho. Erros 403/404 tratados via toast. Estados: loading · empty · erro.
 */
import { useCallback, useEffect, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { listNotices, deleteNotice, type Notice } from "@/lib/cell-notices-api";
import { fetchCellsFull, type CellSummary } from "@/lib/cells-api";
import { formatPublishedAt } from "@/components/minha-celula/format";
import { CentralNoticeForm } from "./CentralNoticeForm";
import type { FlashToast } from "./types";

function originClass(escopo: string): string {
  return escopo === "celula" ? "origem-celula" : "origem-central";
}
function originLabel(escopo: string): string {
  return escopo === "celula" ? "Célula" : "Igreja";
}

export function NoticesPanel({
  token,
  onToast,
  onChanged,
}: {
  token: string;
  onToast: FlashToast;
  onChanged?: () => void;
}) {
  const [cells, setCells] = useState<CellSummary[]>([]);
  const [items, setItems] = useState<Notice[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "reload") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const [noticePage, cellPage] = await Promise.all([
          listNotices(token),
          fetchCellsFull(token).catch(() => ({ items: [] as CellSummary[] })),
        ]);
        setItems(noticePage.items.filter((n) => n.ativo));
        setCells(cellPage.items);
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar os avisos.");
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  async function inactivate(notice: Notice) {
    if (pendingId) return;
    setPendingId(notice.id);
    try {
      await deleteNotice(token, notice.id);
      onToast({ kind: "ok", text: "Aviso inativado." });
      setItems((prev) => prev.filter((n) => n.id !== notice.id));
      onChanged?.();
    } catch (err) {
      onToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível inativar o aviso.",
      });
    } finally {
      setPendingId(null);
    }
  }

  const showSkeleton = loading && !loaded;

  return (
    <div className="central-stack">
      <CentralNoticeForm
        token={token}
        cells={cells}
        onToast={onToast}
        onPublished={(notice) => {
          setItems((prev) => [notice, ...prev]);
          onChanged?.();
        }}
      />

      <section className="card" aria-label="Avisos publicados">
        <div className="panel-title">
          <Icon name="bell" /> Avisos ativos
          {items.length ? <span className="count">· {items.length}</span> : null}
        </div>

        {error ? (
          <DsBanner
            kind="error"
            action={
              <DsButton variant="secondary" onClick={() => void load("initial")} disabled={loading}>
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
          <DsEmptyState illustration={<Icon name="bell" />} title="Nenhum aviso publicado." />
        ) : (
          <div>
            {items.map((n) => (
              <article className={`notice-item ${originClass(n.escopo)}`} key={n.id}>
                <div className="notice-head">
                  <span className="notice-title">{n.titulo}</span>
                  <span className={`pill ${n.escopo === "celula" ? "accent" : "danger"}`}>
                    {originLabel(n.escopo)}
                  </span>
                </div>
                <p className="notice-body">{n.conteudo}</p>
                <div className="notice-foot" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--s3)" }}>
                  <span className="notice-time">{formatPublishedAt(n.publicado_em)}</span>
                  <DsButton
                    variant="tertiary"
                    onClick={() => void inactivate(n)}
                    loading={pendingId === n.id}
                    disabled={pendingId !== null && pendingId !== n.id}
                  >
                    <Icon name="trash" />
                    <span>Inativar</span>
                  </DsButton>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
