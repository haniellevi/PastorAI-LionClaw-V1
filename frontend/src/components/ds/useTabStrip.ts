"use client";

/**
 * Comportamento compartilhado da faixa de abas/nav rolável da fundação
 * (extraído de ds/Tabs.tsx no Gate 6 para reuso pelo ModuleTabs do shell):
 *
 * - revela o item ativo (marcado com data-strip-active="true") rolando APENAS
 *   o scrollLeft do contêiner .ds-tabs-scroll — nunca scrollIntoView, que
 *   deslocaria a página verticalmente;
 * - o limite direito desconta os 44px do véu de continuidade (mask): visível
 *   significa fora do fade;
 * - depois de garantir o ativo, revela o PRÓXIMO item inteiro quando isso não
 *   corta o ativo (Gate 4.1/5.1);
 * - mantém wrap.dataset.atEnd — o véu e o chevron somem no fim do scroll
 *   (Gate 5.2), então o último item fica 100% legível.
 */
import { useEffect, type RefObject } from "react";

export const TABSTRIP_FADE = 44;

export function useTabStrip(
  listRef: RefObject<HTMLElement | null>,
  wrapRef: RefObject<HTMLElement | null>,
  activeKey: string,
) {
  useEffect(() => {
    const list = listRef.current;
    const scroller = list?.parentElement; // .ds-tabs-scroll
    const el = list?.querySelector<HTMLElement>('[data-strip-active="true"]');
    if (!list || !scroller || !el) return;
    const left = el.offsetLeft;
    const right = left + el.offsetWidth;
    const viewLeft = scroller.scrollLeft;
    const viewRight = viewLeft + scroller.clientWidth - TABSTRIP_FADE;
    if (left < viewLeft) scroller.scrollLeft = Math.max(0, left - 12);
    else if (right > viewRight) scroller.scrollLeft = right - (scroller.clientWidth - TABSTRIP_FADE);
    const next = el.nextElementSibling as HTMLElement | null;
    if (next) {
      const needed = next.offsetLeft + next.offsetWidth - (scroller.clientWidth - TABSTRIP_FADE);
      if (needed > scroller.scrollLeft && left >= needed) scroller.scrollLeft = needed;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refs são estáveis; reage à mudança de item ativo
  }, [activeKey]);

  useEffect(() => {
    const scroller = listRef.current?.parentElement;
    const wrap = wrapRef.current;
    if (!scroller || !wrap) return;
    const update = () => {
      const atEnd = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 1;
      wrap.dataset.atEnd = atEnd ? "true" : "false";
      // Gate 6.3: par do início — habilita véu/chevron ESQUERDO quando há
      // conteúdo cortado atrás (scrollLeft > 0). Aditivo: consumidores sem CSS
      // para data-at-start não mudam.
      wrap.dataset.atStart = scroller.scrollLeft <= 0 ? "true" : "false";
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refs são estáveis; efeito de montagem
  }, []);
}
