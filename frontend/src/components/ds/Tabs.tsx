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
import { useEffect, useId, useRef, type ReactNode } from "react";

import { rovingNextIndex, tabDomIds } from "./a11y";

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

  useEffect(() => {
    // Revela a tab ativa rolando APENAS o contêiner horizontal.
    const list = listRef.current;
    const scroller = list?.parentElement; // .ds-tabs-scroll
    const el = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !scroller || !el) return;
    // Véu de continuidade (mask) ocupa os últimos 44px: "visível" à direita
    // significa FORA do véu — o limite direito desconta o fade (Gate 5.2).
    const FADE = 44;
    const left = el.offsetLeft;
    const right = left + el.offsetWidth;
    const viewLeft = scroller.scrollLeft;
    const viewRight = viewLeft + scroller.clientWidth - FADE;
    if (left < viewLeft) scroller.scrollLeft = Math.max(0, left - 12);
    else if (right > viewRight) scroller.scrollLeft = right - (scroller.clientWidth - FADE);
    // Depois de garantir a ativa, revela a PRÓXIMA tab inteira quando isso não
    // corta a ativa (correção Gate 5.1: "Solicitações 2" legível na abertura).
    const next = el.nextElementSibling as HTMLElement | null;
    if (next) {
      const needed = next.offsetLeft + next.offsetWidth - (scroller.clientWidth - FADE);
      if (needed > scroller.scrollLeft && left >= needed) scroller.scrollLeft = needed;
    }
  }, [active]);

  useEffect(() => {
    // Véu e chevron são indicadores de CONTINUIDADE: somem quando o scroll
    // chega ao fim (sem eles, a última tab — "Materiais" — fica 100% legível).
    const scroller = listRef.current?.parentElement;
    const wrap = wrapRef.current;
    if (!scroller || !wrap) return;
    const update = () => {
      const atEnd = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 1;
      wrap.dataset.atEnd = atEnd ? "true" : "false";
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

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
