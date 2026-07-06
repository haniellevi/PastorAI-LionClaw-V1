"use client";

/**
 * US-14 — minhas solicitações (líder). Lista as solicitações do próprio líder com
 * status e a observação da Central (quando houver). Ações do autor:
 *   • Reenviar — apenas em 'ajuste_solicitado' (resubmitRequest);
 *   • Cancelar — em 'aguardando' ou 'ajuste_solicitado' (toast "Solicitação cancelada.").
 * Auto-carrega e recarrega quando `reloadToken` muda (ex.: após criar solicitação).
 * Estados: loading (skeleton) · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  listRequests,
  cancelRequest,
  resubmitRequest,
  type CellRequest,
} from "@/lib/cell-requests-api";
import { formatPublishedAt } from "./format";
import type { FlashToast } from "./types";

const TYPE_LABELS: Record<string, string> = {
  alterar_dia: "Alterar dia",
  alterar_horario: "Alterar horário",
  alterar_endereco: "Alterar endereço",
  alterar_anfitriao: "Alterar anfitrião",
  alterar_auxiliar: "Alterar auxiliar",
  transferir_membro: "Transferir membro",
  remover_membro: "Remover membro",
  multiplicacao: "Multiplicação",
};

const STATUS_META: Record<string, { label: string; tone: PillTone }> = {
  aguardando: { label: "Aguardando", tone: "warn" },
  ajuste_solicitado: { label: "Ajuste solicitado", tone: "accent" },
  aprovada: { label: "Aprovada", tone: "ok" },
  rejeitada: { label: "Rejeitada", tone: "danger" },
  cancelada: { label: "Cancelada", tone: "muted" },
};

const OPEN_STATES = new Set(["aguardando", "ajuste_solicitado"]);

function typeLabel(tipo: string): string {
  return TYPE_LABELS[tipo] ?? tipo;
}

function statusMeta(status: string): { label: string; tone: PillTone } {
  return STATUS_META[status] ?? { label: status, tone: "muted" };
}

export function MyRequestsList({
  token,
  reloadToken,
  onToast,
}: {
  token: string;
  reloadToken: number;
  onToast: FlashToast;
}) {
  const [items, setItems] = useState<CellRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"cancel" | "resubmit" | null>(null);

  const load = useCallback(
    async (mode: "initial" | "reload") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await listRequests(token);
        setItems(page.items);
        setLoaded(true);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar as solicitações.",
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

  async function cancel(req: CellRequest) {
    if (pendingId) return;
    setPendingId(req.id);
    setPendingAction("cancel");
    try {
      await cancelRequest(token, req.id);
      onToast({ kind: "ok", text: "Solicitação cancelada." });
      await load("reload");
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível cancelar a solicitação.";
      onToast({ kind: "err", text });
    } finally {
      setPendingId(null);
      setPendingAction(null);
    }
  }

  async function resubmit(req: CellRequest) {
    if (pendingId) return;
    setPendingId(req.id);
    setPendingAction("resubmit");
    try {
      // Reenvia com o payload existente (já validado na criação); mandar null
      // faria o backend revalidar {} contra o schema estrito e devolver 422.
      await resubmitRequest(token, req.id, req.payload_proposto);
      onToast({ kind: "ok", text: "Solicitação reenviada." });
      await load("reload");
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível reenviar a solicitação.";
      onToast({ kind: "err", text });
    } finally {
      setPendingId(null);
      setPendingAction(null);
    }
  }

  const showSkeleton = loading && !loaded;

  return (
    <section className="card" aria-label="Minhas solicitações">
      <div className="panel-title">
        <Icon name="document" /> Minhas solicitações
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
          <Icon name="document" />
          <p>
            <strong>Nenhuma solicitação enviada.</strong>
          </p>
        </div>
      ) : (
        <div>
          {items.map((req) => {
            const meta = statusMeta(req.status);
            const canCancel = OPEN_STATES.has(req.status);
            const canResubmit = req.status === "ajuste_solicitado";
            const rowBusy = pendingId === req.id;
            return (
              <div className="req-item" key={req.id}>
                <div className="req-head">
                  <span className="req-type">{typeLabel(req.tipo)}</span>
                  <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                </div>
                {req.created_at ? (
                  <div className="req-time">{formatPublishedAt(req.created_at)}</div>
                ) : null}
                {req.observacao_central ? (
                  <div className="req-obs">
                    <Icon name="info" />
                    <span>{req.observacao_central}</span>
                  </div>
                ) : null}
                {canCancel || canResubmit ? (
                  <div className="req-actions">
                    {canResubmit ? (
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => void resubmit(req)}
                        loading={rowBusy && pendingAction === "resubmit"}
                        loadingText="Reenviando…"
                        disabled={pendingId !== null && !rowBusy}
                      >
                        <Icon name="refresh" />
                        <span>Reenviar</span>
                      </Button>
                    ) : null}
                    {canCancel ? (
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => void cancel(req)}
                        loading={rowBusy && pendingAction === "cancel"}
                        loadingText="Cancelando…"
                        disabled={pendingId !== null && !rowBusy}
                      >
                        <Icon name="close" />
                        <span>Cancelar</span>
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
