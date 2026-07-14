"use client";

/**
 * US-17 — Fila de solicitações da Central. Lista as solicitações `aguardando` em
 * master-detail: no desktop, lista à esquerda e detalhe/decisão à direita; no
 * mobile, empilhado (mesmo código-base, `.central-md`). Selecionar abre o
 * RequestDecisionPanel (US-15). Após decidir, o item sai da fila e o painel
 * recarrega. Estados: loading (skeleton) · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { listRequests, type CellRequest } from "@/lib/cell-requests-api";
import { formatPublishedAt } from "@/components/minha-celula/format";
import { RequestDecisionPanel } from "./RequestDecisionPanel";
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

function typeLabel(tipo: string): string {
  return TYPE_LABELS[tipo] ?? tipo;
}

export function RequestsPanel({
  token,
  onToast,
  onChanged,
}: {
  token: string;
  onToast: FlashToast;
  /** Notifica a casca para recarregar os badges do dashboard após uma decisão. */
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<CellRequest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "reload") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await listRequests(token, "aguardando");
        setItems(page.items);
        setSelectedId((prev) => (prev && page.items.some((i) => i.id === prev) ? prev : null));
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar as solicitações.");
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const handleDecided = useCallback(
    (updated: CellRequest) => {
      // A solicitação deixa de estar `aguardando` → sai da fila.
      setItems((prev) => prev.filter((i) => i.id !== updated.id));
      setSelectedId(null);
      onChanged?.();
      void load("reload");
    },
    [load, onChanged],
  );

  const selected = items.find((i) => i.id === selectedId) ?? null;
  const showSkeleton = loading && !loaded;

  return (
    <div className="central-md">
      <section className="card" aria-label="Fila de solicitações">
        <div className="panel-title">
          <Icon name="bell" /> Aguardando
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
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <DsEmptyState illustration={<Icon name="check" />} title="Nenhuma solicitação aguardando." />
        ) : (
          <div>
            {items.map((req) => (
              <button
                type="button"
                key={req.id}
                className={`req-row${selectedId === req.id ? " active" : ""}`}
                onClick={() => setSelectedId(req.id)}
                aria-pressed={selectedId === req.id}
              >
                <span style={{ minWidth: 0 }}>
                  <span className="nm" style={{ display: "block" }}>
                    {typeLabel(req.tipo)}
                  </span>
                  {req.created_at ? (
                    <span className="sub">{formatPublishedAt(req.created_at)}</span>
                  ) : null}
                </span>
                <StatusPill tone="warn">Aguardando</StatusPill>
              </button>
            ))}
          </div>
        )}
      </section>

      {selected ? (
        <RequestDecisionPanel
          key={selected.id}
          token={token}
          request={selected}
          onDecided={handleDecided}
          onToast={onToast}
          onClose={() => setSelectedId(null)}
        />
      ) : (
        <section className="card" aria-label="Detalhe da solicitação">
          <DsEmptyState
            illustration={<Icon name="document" />}
            title="Selecione uma solicitação"
            hint="Escolha um item da fila ao lado para revisar e decidir."
          />
        </section>
      )}
    </div>
  );
}
