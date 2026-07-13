"use client";

/**
 * Toast da fundação (contrato fechado nos Gates 5.1/5.2):
 * - `ok` = role="status" (polite), auto-dismiss com `duration` (padrão 3200ms);
 *   `onDismiss` é OBRIGATÓRIO (união discriminada) — sem ele o toast nunca
 *   sairia da tela;
 * - `err` = role="alert" e persistente: NUNCA auto-dismiss — fecha só pelo
 *   botão (onDismiss opcional);
 * - o timer reage a kind/duration/onDismiss: ok→err limpa o timer na hora
 *   (cleanup do efeito), err→ok cria o timer, mudanças de duration/callback
 *   reiniciam com os valores novos;
 * - `action` opcional (ex.: "Desfazer");
 * - região live persistente: renderize <DsToastRegion> sempre montada.
 */
import { useEffect, type ReactNode } from "react";

import { DsIconButton } from "./IconButton";

/** Região live persistente (fixed bottom, z toast). Monte-a UMA vez por tela. */
export function DsToastRegion({ children }: { children?: ReactNode }) {
  return (
    <div className="ds-toast-region" aria-live="polite" aria-label="Notificações">
      {children}
    </div>
  );
}

interface DsToastBaseProps {
  text: string;
  /** Ação opcional (ex.: botão "Desfazer"). */
  action?: ReactNode;
}

export type DsToastProps =
  | (DsToastBaseProps & {
      kind: "ok";
      /** Auto-dismiss em ms (padrão 3200). */
      duration?: number;
      onDismiss: () => void;
    })
  | (DsToastBaseProps & {
      kind: "err";
      duration?: never;
      onDismiss?: () => void;
    });

export function DsToast(props: DsToastProps) {
  const { kind, text, action } = props;
  const onDismiss = props.onDismiss;
  const duration = kind === "ok" ? (props.duration ?? 3200) : null;

  useEffect(() => {
    // err nunca tem auto-dismiss; a troca ok→err derruba o timer anterior
    // via cleanup (deps mudaram), e err→ok cria o timer do sucesso.
    if (duration === null || !onDismiss) return;
    const t = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(t);
  }, [duration, onDismiss]);

  return (
    <div className={`ds-toast ds-toast--${kind}`} role={kind === "err" ? "alert" : "status"}>
      <span className="ds-toast-icon" aria-hidden="true">
        {kind === "ok" ? (
          <svg viewBox="0 0 20 20" width="18" height="18">
            <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M6.5 10.2l2.4 2.4 4.6-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 20 20" width="18" height="18">
            <path d="M10 2.6L18.6 17H1.4L10 2.6z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M10 8v4.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <circle cx="10" cy="14.7" r="0.9" fill="currentColor" />
          </svg>
        )}
      </span>
      <span className="ds-toast-text">{text}</span>
      {action ? <span className="ds-toast-action">{action}</span> : null}
      {kind === "err" && onDismiss ? (
        <DsIconButton label="Fechar" onClick={onDismiss}>
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
          </svg>
        </DsIconButton>
      ) : null}
    </div>
  );
}
