"use client";

/**
 * Tabs da fundação (DESIGN.md §8 + correções Gate 4.1/5.1):
 * - semântica WAI-ARIA (tablist/tab/tabpanel) com roving tabindex;
 * - setas/Home/End navegam (lógica pura em a11y.ts, coberta por vitest);
 * - alvo mínimo de 44px de altura (CSS .ds-tab);
 * - overflow-x REAL com fade + chevron de continuidade — todas as tabs
 *   alcançáveis por toque e teclado;
 * - IDs únicos por instância via useId (duas Tabs na mesma página nunca
 *   colidem; helper puro tabDomIds coberto por vitest);
 * - aria-controls só quando o tabpanel correspondente existe de fato;
 * - a tab ativa é revelada ajustando SOMENTE o scrollLeft do contêiner
 *   .ds-tabs-scroll — nunca scrollIntoView, que deslocaria a página
 *   verticalmente na montagem (scrollY precisa permanecer 0).
 */
import { useId, useRef, type ReactNode } from "react";

import { rovingNextIndex, tabDomIds } from "./a11y";
import { useTabStrip } from "./useTabStrip";

export interface TabItem {
  id: string;
  label: string;
  badge?: number;
}

export interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  /** Rótulo acessível do conjunto. */
  label: string;
  children?: ReactNode;
}

export function Tabs({ tabs, active, onChange, label, children }: TabsProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const prefix = useId();
  const hasPanel = children !== undefined && children !== null;
  const activeIndex = Math.max(
    0,
    tabs.findIndex((t) => t.id === active),
  );

  // Revelação do item ativo + estado at-end do véu/chevron: comportamento
  // compartilhado da faixa (extraído p/ useTabStrip no Gate 6; regras dos
  // Gates 4.1/5.1/5.2 preservadas — reprovadas em DOM real neste gate).
  useTabStrip(listRef, wrapRef, active);

  function onKeyDown(e: React.KeyboardEvent) {
    const next = rovingNextIndex(activeIndex, tabs.length, e.key);
    if (next === activeIndex) return;
    const alvo = tabs[next];
    if (!alvo) return;
    e.preventDefault();
    onChange(alvo.id);
    const buttons = listRef.current?.querySelectorAll<HTMLElement>('[role="tab"]');
    buttons?.[next]?.focus();
  }

  const activeIds = tabDomIds(prefix, active);

  return (
    <div className="ds-tabs-wrap" ref={wrapRef}>
      <div className="ds-tabs-scroll">
        <div ref={listRef} role="tablist" aria-label={label} className="ds-tabs" onKeyDown={onKeyDown}>
          {tabs.map((t) => {
            const selected = t.id === active;
            const ids = tabDomIds(prefix, t.id);
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={ids.tab}
                aria-selected={selected}
                /* aria-controls só na tab selecionada: o tabpanel monta sob
                   demanda e toda referência ARIA deve apontar p/ nó existente */
                aria-controls={hasPanel && selected ? ids.panel : undefined}
                tabIndex={selected ? 0 : -1}
                data-strip-active={selected ? "true" : undefined}
                className={selected ? "ds-tab ds-tab--active" : "ds-tab"}
                onClick={() => onChange(t.id)}
              >
                {t.label}
                {typeof t.badge === "number" ? <span className="ds-tab-badge">{t.badge}</span> : null}
              </button>
            );
          })}
        </div>
      </div>
      <span className="ds-tabs-chevron" aria-hidden="true">
        ›
      </span>
      {hasPanel ? (
        <div role="tabpanel" id={activeIds.panel} aria-labelledby={activeIds.tab} className="ds-tabpanel">
          {children}
        </div>
      ) : null}
    </div>
  );
}
