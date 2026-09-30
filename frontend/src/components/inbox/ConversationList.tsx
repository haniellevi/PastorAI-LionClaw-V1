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
import { useEffect, useId, useRef } from "react";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import type { Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import {
  contactAvatar,
  displayName,
  effectiveEstado,
  shortTime,
  tipoMarker,
  conversationPill,
  type AgentAvailability,
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
  agentAvailability = "unknown",
  hasConversations = conversations.length > 0,
  partialList = false,
  loadedCount = conversations.length,
  total = conversations.length,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  selfId,
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
  agentAvailability?: AgentAvailability;
  hasConversations?: boolean;
  partialList?: boolean;
  loadedCount?: number;
  total?: number;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  selfId?: string;
}) {
  const searchId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const loadMoreHadFocus = useRef(false);
  useEffect(() => {
    if (loadingMore) return;
    if (!hasMore && loadMoreHadFocus.current && document.activeElement === document.body) {
      searchRef.current?.focus();
    }
    loadMoreHadFocus.current = false;
  }, [hasMore, loadingMore]);
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
          Em espera
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
        <label htmlFor={searchId}>Buscar conversa</label>
        <input
          id={searchId}
          ref={searchRef}
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Nome, telefone ou mensagem"
          aria-label="Buscar conversa"
        />
      </div>

      <p className={partialList ? "ib-coverage" : "sr-only"} role="status" aria-atomic="true">
        {partialList
          ? `${loadedCount} de ${total} conversas carregadas. A busca e os filtros abrangem as conversas carregadas.`
          : `Todas as ${loadedCount} conversas foram carregadas.`}
      </p>
      {conversations.length === 0 ? (
        <DsEmptyState
          title={hasConversations || partialList ? "Nenhuma conversa neste filtro." : "Ainda não há conversas."}
          hint={hasConversations || partialList ? "Ajuste a busca ou escolha Todas." : "As conversas recebidas pelo número oficial aparecerão aqui."}
        />
      ) : (
        conversations.map((c) => {
          const estado = effectiveEstado(c);
          const pill = conversationPill(c, agentAvailability);
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
                <div className="ib-row-state">
                  {estado === "aguardando" ? <Icon name="clock" /> : null}
                  <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                  {estado === "humano" ? (
                    <span className="ib-holder">
                      {c.assumidoPor === selfId ? "Em atendimento por você" : c.assumidoPorNome ? `Responsável: ${c.assumidoPorNome}` : "Responsável não informado"}
                    </span>
                  ) : null}
                </div>
              </div>
            </button>
          );
        })
      )}
      {hasMore && onLoadMore ? (
        <div className="ib-load-more">
          <DsButton variant="secondary" loading={loadingMore} onClick={(event) => {
            loadMoreHadFocus.current = document.activeElement === event.currentTarget;
            onLoadMore();
          }}>
            Carregar mais conversas
          </DsButton>
        </div>
      ) : null}
    </div>
  );
}
