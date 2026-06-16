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
 * O histórico completo é carregado do backend (GET /conversations/{id}/messages)
 * e cada mensagem exibe data/hora (dia da semana, data e hora).
 */
import { useEffect, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import type { ChatMessage, Conversation } from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";

import {
  contactAvatar,
  displayName,
  effectiveEstado,
  estadoPill,
  maskPhone,
  messageStamp,
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

/** Ícone do anexo pela MIME (imagem vs. documento genérico). */
function attachIcon(mime: string): "image" | "document" {
  return mime.startsWith("image/") ? "image" : "document";
}

/** Corpo de uma mensagem: texto puro ou mídia (imagem/arquivo/áudio). */
function MessageBody({ m }: { m: ChatMessage }) {
  if (m.tipo === "imagem") {
    return (
      <>
        {m.mediaUrl ? (
          <a
            href={m.mediaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="msg-img-link"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={m.mediaUrl} alt={m.texto ?? "Imagem"} className="msg-img" />
          </a>
        ) : (
          <span className="msg-media-na">
            <Icon name="image" /> Imagem indisponível
          </span>
        )}
        {m.texto ? <span className="msg-caption">{m.texto}</span> : null}
      </>
    );
  }

  if (m.tipo === "audio") {
    return (
      <>
        {m.mediaUrl ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <audio controls src={m.mediaUrl} className="msg-audio" />
        ) : (
          <span className="msg-media-na">
            <Icon name="alert" /> Áudio indisponível
          </span>
        )}
        {m.texto ? <span className="msg-caption">{m.texto}</span> : null}
      </>
    );
  }

  if (m.tipo === "arquivo") {
    return (
      <>
        {m.mediaUrl ? (
          <a
            href={m.mediaUrl}
            download={m.mediaNome ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="msg-file"
          >
            <Icon name="document" />
            <span className="msg-file-name">{m.mediaNome ?? "Arquivo"}</span>
            <Icon name="download" />
          </a>
        ) : (
          <span className="msg-media-na">
            <Icon name="alert" /> Arquivo indisponível
          </span>
        )}
        {m.texto ? <span className="msg-caption">{m.texto}</span> : null}
      </>
    );
  }

  return <>{m.texto ?? ""}</>;
}

export function ConversationThread({
  conversation,
  selfId,
  holderName,
  degraded,
  busy,
  conflict,
  messages,
  messagesLoading,
  onAssume,
  onReturn,
  onSend,
  onSendMedia,
}: {
  conversation: Conversation;
  selfId: string;
  holderName: string | null;
  degraded: boolean;
  busy: boolean;
  conflict: string | null;
  messages: ChatMessage[];
  messagesLoading: boolean;
  onAssume: (c: Conversation) => void;
  onReturn: (c: Conversation) => void;
  onSend: (c: Conversation, text: string) => void;
  onSendMedia: (c: Conversation, file: File, caption?: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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
    setPendingFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [conversation.id]);
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [conversation.id, messages.length]);

  function clearAttachment() {
    setPendingFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canCompose || sending) return;

    // Anexo pendente: envia a mídia (com a legenda atual, se houver).
    if (pendingFile) {
      setSending(true);
      try {
        const ok = await onSendMedia(conversation, pendingFile, draft.trim() || undefined);
        if (ok) {
          clearAttachment();
          setDraft("");
        }
      } finally {
        setSending(false);
      }
      return;
    }

    const value = draft.trim();
    if (!value) return;
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
        {messagesLoading && messages.length === 0 ? (
          <p
            className="sub"
            style={{ textAlign: "center", color: "var(--faint)", marginTop: "var(--s4)" }}
          >
            Carregando conversa…
          </p>
        ) : messages.length === 0 ? (
          <div className="empty-pane" style={{ padding: "var(--s5)" }}>
            <Icon name="chat" />
            <p className="sub">Ainda não há mensagens nesta conversa.</p>
          </div>
        ) : (
          messages.map((m) => (
            <div
              className={`msg ${m.direcao === "out" ? "out" : "in"}${
                m.tipo !== "texto" ? " msg-media" : ""
              }`}
              key={m.id}
            >
              <MessageBody m={m} />
              <time>{messageStamp(m.criadoEm)}</time>
            </div>
          ))
        )}
      </div>

      {pendingFile ? (
        <div className="attach-chip">
          <Icon name={attachIcon(pendingFile.type)} />
          <span className="attach-name">{pendingFile.name}</span>
          <button
            type="button"
            className="attach-x"
            onClick={clearAttachment}
            aria-label="Remover anexo"
            disabled={sending}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      ) : null}

      <form className="thread-foot" onSubmit={submit}>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip,audio/*"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            if (f) setPendingFile(f);
          }}
          disabled={!canCompose || sending}
        />
        <button
          type="button"
          className="btn btn-icon"
          onClick={() => fileInputRef.current?.click()}
          disabled={!canCompose || sending}
          title="Anexar imagem ou arquivo"
          aria-label="Anexar imagem ou arquivo"
        >
          <Icon name="paperclip" />
        </button>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            degraded
              ? "Envio desabilitado — WhatsApp indisponível"
              : !isMine
                ? "Assuma o atendimento para responder"
                : pendingFile
                  ? "Adicione uma legenda (opcional)…"
                  : "Escreva uma resposta…"
          }
          disabled={!canCompose || sending}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!canCompose || sending || (!pendingFile && draft.trim().length === 0)}
        >
          <Icon name="send" />
          <span>{sending ? "Enviando…" : "Enviar"}</span>
        </button>
      </form>
    </div>
  );
}
