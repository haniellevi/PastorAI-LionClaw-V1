"use client";

/**
 * Dialog da fundação (DESIGN.md §8): mesmo primitive e mesma semântica no
 * desktop (central) e no mobile (sheet ancorada embaixo via prop `sheet` —
 * em telas ≤860px o CSS também ancora automaticamente).
 *
 * Acessibilidade (obrigatória no Gate 5):
 * - role="dialog" + aria-modal="true" + aria-labelledby;
 * - Esc fecha;
 * - focus trap (Tab/Shift+Tab ciclam dentro do dialog — lógica em a11y.ts);
 * - foco inicial no primeiro focável (ou no próprio painel);
 * - foco retorna ao elemento que abriu;
 * - scroll lock no body enquanto aberto.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";

import { getFocusable, trapNextIndex } from "./a11y";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  /** Força apresentação em sheet (mobile); sem a prop, o CSS decide por media query. */
  sheet?: boolean;
  children: ReactNode;
  /** Rodapé (ações). A ação principal fica próxima do final do fluxo. */
  footer?: ReactNode;
}

export function Dialog({ open, onClose, title, description, sheet = false, children, footer }: DialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const descId = useId();

  // Gate 5.1: o efeito de abertura depende só da TRANSIÇÃO de `open`. Um pai
  // que recria onClose a cada render (função inline) não pode reiniciar o
  // efeito — isso roubava o foco de volta ao primeiro focável.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;

    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Foco inicial coerente: um alvo MARCADO com [data-autofocus] (Gate 7.1 —
    // ex.: o textarea do modal de mensagem) tem prioridade; sem marcação, o
    // primeiro focável do conteúdo (comportamento original de todos os demais
    // consumidores); fallback no painel.
    const preferred = panel.querySelector<HTMLElement>("[data-autofocus]");
    const focusables = getFocusable(panel);
    (preferred ?? focusables[0] ?? panel).focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = getFocusable(panel!);
      const current = items.indexOf(document.activeElement as HTMLElement);
      const next = trapNextIndex(current, items.length, e.shiftKey);
      // Trap: o Tab nunca sai do dialog.
      e.preventDefault();
      if (next >= 0) items[next]?.focus();
      else panel!.focus();
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="ds-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        className={sheet ? "ds-dialog ds-dialog--sheet" : "ds-dialog"}
        tabIndex={-1}
      >
        {sheet ? <div className="ds-sheet-grip" aria-hidden="true" /> : null}
        <header className="ds-dialog-head">
          <div>
            <h2 id={titleId} className="ds-dialog-title">
              {title}
            </h2>
            {description ? (
              <p id={descId} className="ds-dialog-desc">
                {description}
              </p>
            ) : null}
          </div>
          <button type="button" className="ds-iconbtn ds-dialog-close" aria-label="Fechar" onClick={onClose}>
            <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
              <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
            </svg>
          </button>
        </header>
        <div className="ds-dialog-body">{children}</div>
        {footer ? <footer className="ds-dialog-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}
