"use client";

/**
 * Assistente do sistema no painel (RF-47, US-41).
 *
 * Botão no cabeçalho do shell que abre uma conversa em Dialog (sheet no
 * celular). O histórico vive só na memória do launcher: fechar a janela não
 * apaga a conversa; sair da sessão apaga (o PRD não prevê persistência no MVP).
 * Quem autoriza e filtra as telas sugeridas é o servidor; a tela ainda confere
 * se a rota existe e se o usuário a abre no painel, por segurança extra.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog } from "@/components/ds/Dialog";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsField } from "@/components/ds/Field";
import { AssistantError, SessionExpiredError, sendAssistantMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";

import "./assistente.css";

const MAX_TEXTO = 2000;

type Mensagem =
  | { id: number; autor: "usuario"; texto: string }
  | { id: number; autor: "assistente"; texto: string; telas: string[] };

type Falha = { kind: "forbidden" | "unavailable" | "invalid"; message: string };

interface PainelProps {
  token: string;
  tenantId: string;
  /** Tela existe e o usuário a abre neste painel. */
  canOpenScreen: (tela: string) => boolean;
  onExpired: () => void;
}

export function AssistentePainel({ token, tenantId, canOpenScreen, onExpired }: PainelProps) {
  const [open, setOpen] = useState(false);
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [falha, setFalha] = useState<Falha | null>(null);
  const [ultimo, setUltimo] = useState("");
  const nextId = useRef(1);
  const locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(true);
  const logRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      controller.current?.abort();
    };
  }, []);

  // Mantém a mensagem mais recente à vista.
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [mensagens, enviando, falha, open]);

  const bloqueado = falha?.kind === "forbidden";

  async function enviar(conteudo: string, repetindo: boolean) {
    if (locked.current || bloqueado) return;
    const limpo = conteudo.trim();
    if (!limpo) return;
    formRef.current?.querySelector("textarea")?.focus();
    locked.current = true;
    setEnviando(true);
    setFalha(null);
    setUltimo(limpo);
    const messageId = repetindo ? null : nextId.current++;
    if (messageId !== null) {
      setMensagens((atual) => [...atual, { id: messageId, autor: "usuario", texto: limpo }]);
      setTexto("");
    }
    const abort = new AbortController();
    controller.current = abort;
    try {
      const reply = await sendAssistantMessage(token, tenantId, limpo, abort.signal);
      if (!active.current) return;
      const replyId = nextId.current++;
      setMensagens((atual) => [
        ...atual,
        {
          id: replyId,
          autor: "assistente",
          texto: reply.resposta,
          telas: [...new Set(reply.telasSugeridas)],
        },
      ]);
    } catch (error) {
      if (!active.current || (error instanceof DOMException && error.name === "AbortError")) return;
      if (error instanceof SessionExpiredError) {
        onExpired();
        return;
      }
      if (error instanceof AssistantError && error.kind === "invalid") {
        setTexto((atual) => atual || limpo);
        if (messageId !== null) {
          setMensagens((atual) => atual.filter((m) => m.id !== messageId));
        }
      }
      setFalha(
        error instanceof AssistantError
          ? { kind: error.kind, message: error.message }
          : { kind: "unavailable", message: "Não foi possível conectar. Tente novamente." },
      );
    } finally {
      locked.current = false;
      if (active.current) setEnviando(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void enviar(texto, false);
  }

  return (
    <>
      <button
        type="button"
        className="ds-btn ds-btn--secondary assistente-trigger"
        aria-label="Abrir assistente do sistema"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        <Icon name="sparkles" size={18} />
        <span className="assistente-trigger-text">Assistente</span>
      </button>
      {/* Portal no body: a topbar é sticky (z-index 5) e prenderia o overlay
          abaixo da bottom-nav no celular, escondendo o botão Enviar. */}
      {open
        ? createPortal(
            <Dialog
              open={open}
              onClose={() => setOpen(false)}
              title="Assistente do sistema"
              description="Pergunte como usar o painel. Ele só indica telas que o seu acesso permite."
              className="assistente-dialog"
              footer={
                <form
                  ref={formRef}
                  className="assistente-form"
                  onSubmit={onSubmit}
                  aria-label="Enviar pergunta"
                >
                  <DsField
                    as="textarea"
                    label="Sua pergunta"
                    rows={2}
                    maxLength={MAX_TEXTO}
                    value={texto}
                    disabled={bloqueado}
                    data-autofocus
                    onChange={(event) => setTexto(event.target.value)}
                    onKeyDown={(event) => {
                      // Ctrl/Cmd+Enter envia; Enter sozinho quebra a linha.
                      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                        event.preventDefault();
                        void enviar(texto, false);
                      }
                    }}
                    helper="Ctrl+Enter envia."
                  />
                  <DsButton
                    type="submit"
                    loading={enviando}
                    disabled={bloqueado || enviando || texto.trim() === ""}
                  >
                    {enviando ? "Carregando…" : "Enviar"}
                  </DsButton>
                </form>
              }
            >
              <div
                ref={logRef}
                className="assistente-log"
                role="log"
                aria-label="Conversa com o assistente"
                aria-live="polite"
                tabIndex={0}
              >
                {mensagens.length === 0 && !enviando && !falha ? (
                  <DsEmptyState
                    title="Nenhuma pergunta ainda"
                    hint="Por exemplo: onde vejo as pendências de hoje?"
                  />
                ) : null}
                {mensagens.map((m) => {
                  const telas = m.autor === "assistente" ? m.telas.filter(canOpenScreen) : [];
                  return (
                    <article
                      key={m.id}
                      className={`assistente-msg assistente-msg--${m.autor}`}
                      aria-label={m.autor === "usuario" ? "Você" : "Assistente"}
                    >
                      <p className="assistente-msg-autor">
                        {m.autor === "usuario" ? "Você" : "Assistente"}
                      </p>
                      <p className="assistente-msg-texto">{m.texto}</p>
                      {telas.length > 0 ? (
                        <ul className="assistente-telas" aria-label="Telas sugeridas">
                          {telas.map((tela) => (
                            <li key={tela}>
                              <a href={`#${tela}`} onClick={() => setOpen(false)}>
                                {SCREEN_META[tela]?.title ?? tela}
                              </a>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </article>
                  );
                })}
                {enviando ? (
                  <p className="assistente-pensando">O assistente está respondendo…</p>
                ) : null}
              </div>
              {falha ? (
                <DsBanner
                  kind={falha.kind === "forbidden" ? "warning" : "error"}
                  action={
                    falha.kind === "unavailable" && ultimo ? (
                      <DsButton variant="tertiary" onClick={() => void enviar(ultimo, true)}>
                        Tentar novamente
                      </DsButton>
                    ) : undefined
                  }
                >
                  {falha.message}
                </DsBanner>
              ) : null}
            </Dialog>,
            document.body,
          )
        : null}
    </>
  );
}

/** Ligação com a sessão: igreja e token vêm do auth, nunca da tela. */
export function AssistenteLauncher({
  canOpenScreen,
}: {
  canOpenScreen: (tela: string) => boolean;
}) {
  const { token, user, expireSession } = useAuth();
  if (!token || !user) return null;
  return (
    <AssistentePainel
      key={`${user.churchId}:${user.appUserId}:${token}`}
      token={token}
      tenantId={user.churchId}
      canOpenScreen={canOpenScreen}
      onExpired={expireSession}
    />
  );
}
