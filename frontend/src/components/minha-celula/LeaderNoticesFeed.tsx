"use client";

/**
 * US-12B — feed de avisos na visão do líder: da célula (azul) + da igreja/Central
 * (vermelho), do mais recente para o mais antigo. O líder pode INATIVAR os avisos
 * da própria célula (deleteNotice → toast). Sem edição no MVP (inativa + cria novo).
 * Auto-carrega e recarrega quando `reloadToken` muda. Estados: loading · empty · erro.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { listNotices, deleteNotice, type Notice } from "@/lib/cell-notices-api";
import { formatPublishedAt } from "./format";
import type { FlashToast } from "./types";

/** célula → azul; igreja/central → vermelho. */
function originClass(escopo: string): string {
  return escopo === "celula" ? "origem-celula" : "origem-central";
}

function originLabel(escopo: string): string {
  return escopo === "celula" ? "Célula" : "Central";
}

export function LeaderNoticesFeed({
  token,
  reloadToken,
  onToast,
}: {
  token: string;
  reloadToken: number;
  onToast: FlashToast;
}) {
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
        const page = await listNotices(token);
        setItems(page.items.filter((n) => n.ativo));
        setLoaded(true);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar os avisos.",
        );
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load(reloadToken === 0 ? "initial" : "reload");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, reloadToken]);

  async function inactivate(notice: Notice) {
    if (pendingId) return;
    setPendingId(notice.id);
    try {
      await deleteNotice(token, notice.id);
      onToast({ kind: "ok", text: "Aviso inativado." });
      await load("reload");
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível inativar o aviso.";
      onToast({ kind: "err", text });
    } finally {
      setPendingId(null);
    }
  }

  const showSkeleton = loading && !loaded;

  return (
    <section className="card" aria-label="Avisos">
      <div className="panel-title">
        <Icon name="bell" /> Avisos
        {items.length ? <span className="count">· {items.length}</span> : null}
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("initial")}
            disabled={loading}
          >
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
      ) : items.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="bell" />
          <p>
            <strong>Nenhum aviso publicado.</strong>
          </p>
        </div>
      ) : (
        <div>
          {items.map((n) => {
            const canInactivate = n.escopo === "celula";
            return (
              <article className={`notice-item ${originClass(n.escopo)}`} key={n.id}>
                <div className="notice-head">
                  <span className="notice-title">{n.titulo}</span>
                  <span className={`pill ${n.escopo === "celula" ? "accent" : "danger"}`}>
                    {originLabel(n.escopo)}
                  </span>
                </div>
                <p className="notice-body">{n.conteudo}</p>
                <div className="notice-foot">
                  <span className="notice-time">{formatPublishedAt(n.publicado_em)}</span>
                  {canInactivate ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void inactivate(n)}
                      loading={pendingId === n.id}
                      loadingText="Inativando…"
                      disabled={pendingId !== null && pendingId !== n.id}
                    >
                      <Icon name="trash" />
                      <span>Inativar</span>
                    </Button>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
