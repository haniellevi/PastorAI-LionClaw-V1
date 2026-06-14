"use client";

/**
 * conversation-list — coluna esquerda do inbox (estados default/active).
 * Filtra por Todas / Aguardando / IA e abre a thread ao clicar (US-11).
 * Estado vazio (empty-state) quando não há conversas no filtro.
 */
import { StatusPill } from "@/components/dashboard/StatusPill";
import type { Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import {
  effectiveEstado,
  estadoPill,
  maskPhone,
  phoneAvatar,
  shortTime,
} from "./conversation-format";

export type ConvFilter = "todas" | "aguardando" | "ia";

export function ConversationList({
  conversations,
  selectedId,
  filter,
  waitingCount,
  now,
  onSelect,
  onFilter,
}: {
  conversations: Conversation[];
  selectedId: string | null;
  filter: ConvFilter;
  waitingCount: number;
  now: number;
  onSelect: (id: string) => void;
  onFilter: (filter: ConvFilter) => void;
}) {
  return (
    <div className="conv-list">
      <div className="conv-filter">
        <div className="tabs" style={{ flex: 1 }}>
          <button
            type="button"
            className={`tab${filter === "todas" ? " active" : ""}`}
            onClick={() => onFilter("todas")}
          >
            Todas
          </button>
          <button
            type="button"
            className={`tab${filter === "aguardando" ? " active" : ""}`}
            onClick={() => onFilter("aguardando")}
          >
            Aguardando {waitingCount > 0 ? <span className="num">{waitingCount}</span> : null}
          </button>
          <button
            type="button"
            className={`tab${filter === "ia" ? " active" : ""}`}
            onClick={() => onFilter("ia")}
          >
            IA
          </button>
        </div>
      </div>

      {conversations.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="chat" />
          <p>
            <strong>Nenhuma conversa neste filtro.</strong>
          </p>
        </div>
      ) : (
        conversations.map((c) => {
          const estado = effectiveEstado(c);
          const pill = estadoPill(estado);
          return (
            <button
              type="button"
              key={c.id}
              className={`conv${c.id === selectedId ? " active" : ""}`}
              onClick={() => onSelect(c.id)}
            >
              <span className="av">{phoneAvatar(c.telefone)}</span>
              <div className="conv-main">
                <div className="conv-top">
                  <strong>{maskPhone(c.telefone)}</strong>
                  <time>{shortTime(c.assumidoEm ?? c.esperaDesde, now)}</time>
                </div>
                <div className="snippet">
                  {c.ultimaMensagem ?? "Sem mensagens ainda"}
                </div>
                <div style={{ marginTop: 5, display: "flex", gap: 6, alignItems: "center" }}>
                  <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                  {c.naoLidas > 0 ? (
                    <span className="num" aria-label={`${c.naoLidas} não lidas`}>
                      {c.naoLidas}
                    </span>
                  ) : null}
                </div>
              </div>
            </button>
          );
        })
      )}
    </div>
  );
}
