"use client";

/**
 * conversation-list — coluna esquerda do inbox (estados default/active).
 * Filtra por Todas / Aguardando / IA e abre a thread ao clicar (US-11).
 * Estado vazio (empty-state) quando não há conversas no filtro.
 *
 * Gate 8 (Diamante Lapidado): linhas contínuas com borda 1px; seleção por
 * selection-soft + aria-current; "aguardando" comunicado por ÍCONE + TEXTO
 * (nunca só cor). Nenhum filtro, busca, dado ou callback mudou.
 */
import { DsEmptyState } from "@/components/ds/EmptyState";
import type { Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import {
  contactAvatar,
  displayName,
  effectiveEstado,
  shortTime,
  tipoMarker,
} from "./conversation-format";

export type ConvFilter = "todas" | "aguardando" | "ia";

export function ConversationList({
  conversations,
  selectedId,
  filter,
  waitingCount,
  now,
  search,
  onSelect,
  onFilter,
  onSearch,
}: {
  conversations: Conversation[];
  selectedId: string | null;
  filter: ConvFilter;
  waitingCount: number;
  now: number;
  search: string;
  onSelect: (id: string) => void;
  onFilter: (filter: ConvFilter) => void;
  onSearch: (value: string) => void;
}) {
  return (
    <div className="conv-list">
      <div className="ib-filter" role="group" aria-label="Filtrar conversas">
        <button
          type="button"
          className={`ib-filter-btn${filter === "todas" ? " active" : ""}`}
          aria-pressed={filter === "todas"}
          onClick={() => onFilter("todas")}
        >
          Todas
        </button>
        <button
          type="button"
          className={`ib-filter-btn${filter === "aguardando" ? " active" : ""}`}
          aria-pressed={filter === "aguardando"}
          onClick={() => onFilter("aguardando")}
        >
          Aguardando
          {waitingCount > 0 ? <span className="ib-filter-num">{waitingCount}</span> : null}
        </button>
        <button
          type="button"
          className={`ib-filter-btn${filter === "ia" ? " active" : ""}`}
          aria-pressed={filter === "ia"}
          onClick={() => onFilter("ia")}
        >
          IA
        </button>
      </div>

      <div className="ib-search">
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Buscar por nome, telefone ou mensagem…"
          aria-label="Buscar conversa"
        />
      </div>

      {conversations.length === 0 ? (
        <DsEmptyState
          title="Nenhuma conversa encontrada."
          hint="Ajuste o filtro ou a busca para ver outras conversas."
        />
      ) : (
        conversations.map((c) => {
          const estado = effectiveEstado(c);
          const marker = tipoMarker(c);
          const active = c.id === selectedId;
          return (
            <button
              type="button"
              key={c.id}
              className={`conv${active ? " active" : ""}`}
              aria-current={active ? "true" : undefined}
              onClick={() => onSelect(c.id)}
            >
              <span className="av" aria-hidden="true">
                {contactAvatar(c)}
              </span>
              <div className="conv-main">
                <div className="conv-top">
                  <strong>{displayName(c)}</strong>
                  {marker ? (
                    <span className={`conv-tipo${marker.csim ? " csim" : ""}`}>
                      {marker.label}
                    </span>
                  ) : null}
                  <time>{shortTime(c.atualizadoEm ?? c.assumidoEm ?? c.esperaDesde, now)}</time>
                </div>
                <div className="conv-sub">
                  <span className="snippet">
                    {c.ultimaMensagem ?? "Sem mensagens ainda"}
                  </span>
                  {c.naoLidas > 0 ? (
                    <span className="conv-badge" aria-label={`${c.naoLidas} não lidas`}>
                      {c.naoLidas}
                    </span>
                  ) : null}
                </div>
                {estado === "aguardando" ? (
                  // Gate 8: aguardando por ÍCONE + TEXTO (nunca só cor).
                  <span className="ib-wait">
                    <Icon name="clock" />
                    Aguardando atendimento
                  </span>
                ) : null}
              </div>
            </button>
          );
        })
      )}
    </div>
  );
}
