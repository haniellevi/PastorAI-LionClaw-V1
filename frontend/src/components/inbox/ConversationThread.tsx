"use client";

/**
 * conversation-thread — coluna direita do inbox (estados ia-active/human/waiting).
 * Mostra cabeçalho do contato, banner de controle (IA × humano), o histórico
 * disponível e o compositor de resposta humana.
 *
 * Ações de handoff (US-12/US-13):
 *  - "Assumir (pausar IA)" → POST handoff {to: human};
 *  - "Devolver para a IA"  → POST handoff {to: ia}.
 * Quando outro humano já detém a conversa, o controle reflete o `assumidoPor`
 * real (conflito) e o botão de assumir fica indisponível.
 *
 * Degradação (banner): com o WhatsApp offline/reconectando, o envio é desativado.
 * O endpoint de persistência da resposta humana chega com a integração do
 * assistente (sprint-017); aqui o envio ecoa localmente na thread.
 */
import { useEffect, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import type { Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import {
  contactAvatar,
  displayName,
  effectiveEstado,
  estadoPill,
  maskPhone,
} from "./conversation-format";

interface ThreadCopy {
  bannerClass: "active" | "human";
  bannerText: string;
}

function threadCopy(estado: "ia" | "humano" | "aguardando"): ThreadCopy {
  if (estado === "humano") {
    return {
      bannerClass: "human",
      bannerText:
        "Atendimento sob controle humano. A IA está pausada nesta conversa.",
    };
  }
  if (estado === "aguardando") {
    return {
      bannerClass: "human",
      bannerText:
        "Atendimento aguardando ação humana. A IA não responderá enquanto estiver pausada.",
    };
  }
  return {
    bannerClass: "active",
    bannerText: "A IA está conduzindo este atendimento automaticamente.",
  };
}

export function ConversationThread({
  conversation,
  selfId,
  holderName,
  degraded,
  busy,
  conflict,
  localReplies,
  onAssume,
  onReturn,
  onSend,
}: {
  conversation: Conversation;
  selfId: string;
  holderName: string | null;
  degraded: boolean;
  busy: boolean;
  conflict: string | null;
  localReplies: string[];
  onAssume: (c: Conversation) => void;
  onReturn: (c: Conversation) => void;
  onSend: (c: Conversation, text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const estado = effectiveEstado(conversation);
  const pill = estadoPill(estado);
  const copy = threadCopy(estado);

  const holder = conversation.assumidoPor;
  const isMine = estado === "humano" && holder === selfId;
  const heldByOther = estado === "humano" && holder !== null && holder !== selfId;
  const canCompose = isMine && !degraded;

  // Auto-scroll ao trocar de conversa / ao ecoar uma resposta.
  useEffect(() => {
    setDraft("");
  }, [conversation.id]);
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [conversation.id, localReplies.length]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = draft.trim();
    if (!value || !canCompose) return;
    onSend(conversation, value);
    setDraft("");
  }

  return (
    <div className="conv-thread">
      <div className="thread-head">
        <span className="av">{contactAvatar(conversation)}</span>
        <div className="who">
          <strong>{displayName(conversation)}</strong>
          <span className="mono">
            {conversation.nome
              ? maskPhone(conversation.telefone)
              : "Contato do WhatsApp oficial"}
          </span>
        </div>
        <div className="ctrl">
          <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
          {isMine ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => onReturn(conversation)}
              disabled={busy}
            >
              <Icon name="sparkles" />
              <span>Devolver para a IA</span>
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => onAssume(conversation)}
              disabled={busy || heldByOther}
              title={
                heldByOther
                  ? "Conversa já assumida por outro líder"
                  : "Assumir o atendimento e pausar a IA"
              }
            >
              <Icon name="user" />
              <span>Assumir (pausar IA)</span>
            </button>
          )}
        </div>
      </div>

      <div className={`ia-banner ${copy.bannerClass}`}>
        <Icon name={estado === "ia" ? "sparkles" : "user"} />
        <span>{copy.bannerText}</span>
      </div>

      {heldByOther ? (
        <div className="degraded-banner">
          <Icon name="alert" />
          <span>
            {conflict ??
              `Em atendimento por ${holderName ?? "outro líder"}. Você não pode assumir agora.`}
          </span>
        </div>
      ) : null}

      {degraded ? (
        <div className="degraded-banner">
          <Icon name="alert" />
          <span>
            WhatsApp indisponível (offline ou reconectando). O envio de respostas está
            desabilitado até a conexão ser restabelecida.
          </span>
        </div>
      ) : null}

      <div className="thread-body" ref={bodyRef}>
        {conversation.ultimaMensagem ? (
          <div className="msg in">
            <span className="tag">Contato</span>
            {conversation.ultimaMensagem}
          </div>
        ) : (
          <div className="empty-pane" style={{ padding: "var(--s5)" }}>
            <Icon name="chat" />
            <p className="sub">Ainda não há mensagens nesta conversa.</p>
          </div>
        )}

        {localReplies.map((text, i) => (
          <div className="msg out" key={i}>
            <span className="tag">Você</span>
            {text}
          </div>
        ))}

        <p className="sub" style={{ textAlign: "center", color: "var(--faint)", marginTop: "var(--s2)" }}>
          O histórico completo da conversa chega com o painel do assistente.
        </p>
      </div>

      <form className="thread-foot" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            degraded
              ? "Envio desabilitado — WhatsApp indisponível"
              : isMine
                ? "Escreva uma resposta…"
                : "Assuma o atendimento para responder"
          }
          disabled={!canCompose}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!canCompose || draft.trim().length === 0}
        >
          <Icon name="send" />
          <span>Enviar</span>
        </button>
      </form>
    </div>
  );
}
