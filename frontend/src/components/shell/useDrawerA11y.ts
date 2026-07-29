"use client";

/**
 * Acessibilidade do drawer mobile da sidebar (Gate 6/6.1). Reusa a lógica de
 * foco/modal da fundação (ds/a11y.ts — a mesma do ds/Dialog):
 *
 * Fechado em mobile: a sidebar (translateX(-100%)) recebe `inert` — some do
 * tab order e da árvore de acessibilidade; ao cruzar para desktop o atributo é
 * removido (sidebar fixa volta a ser interativa).
 *
 * Aberto:
 * - foco inicial no primeiro focável do drawer;
 * - focus trap (Tab/Shift+Tab ciclam dentro — trapNextIndex);
 * - Escape fecha; foco retorna ao gatilho ("Mais"/hambúrguer);
 * - conteúdo atrás (irmãos do drawer no .app, exceto o backdrop) fica `inert`;
 * - scroll REAL bloqueado: o scroller é a .screen (não só o body);
 * - cruzou o breakpoint para desktop com o drawer aberto → fecha e o cleanup
 *   remove todos os locks/inert.
 *
 * Não altera rota nem estado global — só efeitos de UI do próprio shell.
 */
import { useEffect, useRef } from "react";

import { getFocusable, trapNextIndex } from "@/components/ds/a11y";
import { lockScroll } from "@/components/ds/scrollLock";

/** id do <nav> da sidebar — alvo do aria-controls dos gatilhos ("Mais"/hambúrguer). */
export const SHELL_DRAWER_ID = "shell-drawer";
/** Breakpoint do shell (par do @media max-width: 860px do globals.css). */
export const DRAWER_MEDIA_MOBILE = "(max-width: 860px)";

/**
 * "Colapsada de verdade" (rail 64px, ícone-only) — Gate 6.2: o drawer mobile
 * NUNCA abre colapsado, mesmo que a preferência de desktop siga colapsada
 * depois de um resize; só conta como colapsada quando não há drawer mobile
 * aberto. Fonte ÚNICA usada pela classe CSS (drawerSidebarClass) E por
 * qualquer lógica de UI que dependa do rail 64px (ex.: o flyout do tooltip
 * colapsado em Sidebar.tsx) — evita as duas lógicas divergirem (revisão
 * externa M7B-Visual-W1: o flyout usava só `collapsed`, ignorando
 * `mobileOpen`, e aparecia errado dentro do drawer mobile aberto).
 */
export function isDesktopCollapsed(collapsed: boolean, mobileOpen: boolean): boolean {
  return collapsed && !mobileOpen;
}

/** Classe da sidebar. Pura para regressão em vitest. */
export function drawerSidebarClass(collapsed: boolean, mobileOpen: boolean): string {
  return `sidebar${isDesktopCollapsed(collapsed, mobileOpen) ? " collapsed" : ""}${mobileOpen ? " open" : ""}`;
}

export function useDrawerA11y(open: boolean, onClose: () => void) {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Fechado em mobile: sidebar fora do tab order / árvore de acessibilidade.
  useEffect(() => {
    const drawer = document.getElementById(SHELL_DRAWER_ID);
    if (!drawer) return;
    const mq = window.matchMedia(DRAWER_MEDIA_MOBILE);
    const apply = () => {
      if (mq.matches && !open) drawer.setAttribute("inert", "");
      else drawer.removeAttribute("inert");
    };
    apply();
    mq.addEventListener("change", apply);
    return () => {
      mq.removeEventListener("change", apply);
      drawer.removeAttribute("inert");
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const drawer = document.getElementById(SHELL_DRAWER_ID);
    if (!drawer) return;
    const opener = document.activeElement as HTMLElement | null;

    // Scroll lock no scroller REAL (.screen) além do body, pelo coordenador
    // compartilhado (ds/scrollLock): com um Dialog aberto por cima, só a última
    // liberação restaura — fechar o drawer primeiro não destrava a página.
    const unlockScroll = lockScroll();

    // Conteúdo atrás inerte: irmãos do drawer no .app (main, bottom-nav…),
    // exceto o backdrop — que precisa continuar clicável para fechar.
    const inerted: Element[] = [];
    drawer.closest(".app")?.querySelectorAll(":scope > *").forEach((el) => {
      if (el === drawer || el.classList.contains("drawer-backdrop")) return;
      if (el.hasAttribute("inert")) return;
      el.setAttribute("inert", "");
      inerted.push(el);
    });

    // Foco inicial: primeiro focável; fallback no próprio drawer (tabIndex=-1).
    const focusables = getFocusable(drawer);
    (focusables[0] ?? drawer).focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = getFocusable(drawer!);
      const current = items.indexOf(document.activeElement as HTMLElement);
      const next = trapNextIndex(current, items.length, e.shiftKey);
      e.preventDefault();
      if (next >= 0) items[next]?.focus();
      else drawer!.focus();
    }
    document.addEventListener("keydown", onKeyDown, true);

    // Cruzou para desktop com o drawer aberto → fecha (cleanup desfaz tudo).
    const mqDesktop = window.matchMedia(DRAWER_MEDIA_MOBILE);
    const onMq = () => {
      if (!mqDesktop.matches) onCloseRef.current();
    };
    mqDesktop.addEventListener("change", onMq);

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      mqDesktop.removeEventListener("change", onMq);
      inerted.forEach((el) => el.removeAttribute("inert"));
      unlockScroll();
      // Gate 6.2: o foco tem de terminar em elemento VISÍVEL. Após resize para
      // desktop o gatilho mobile ("Mais"/hambúrguer) some (display:none) —
      // nesse caso o foco vai para o primeiro focável da sidebar (agora fixa).
      const openerVisible = opener && opener.isConnected && opener.offsetParent !== null;
      if (openerVisible) opener.focus();
      else (getFocusable(drawer)[0] ?? drawer).focus();
    };
  }, [open]);
}
