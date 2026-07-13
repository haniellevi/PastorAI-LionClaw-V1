/**
 * Utilitários de acessibilidade da fundação (Gate 5).
 * Lógica pura separada dos componentes para permitir teste unitário (vitest)
 * sem ambiente DOM.
 */

export const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

/** Elementos focáveis visíveis dentro de um contêiner (ordem do DOM). */
export function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

/**
 * Índice-alvo do focus trap para um Tab/Shift+Tab dado o índice atual.
 * -1 = foco fora da lista (ex.: acabou de abrir) → vai para o primeiro
 * (ou último, com Shift). Lista vazia → -1 (nada a focar).
 */
export function trapNextIndex(current: number, count: number, shift: boolean): number {
  if (count <= 0) return -1;
  if (current === -1) return shift ? count - 1 : 0;
  const next = current + (shift ? -1 : 1);
  if (next < 0) return count - 1;
  if (next >= count) return 0;
  return next;
}

/**
 * IDs de DOM de uma tab e do seu painel, prefixados por instância (useId).
 * Puro para permitir regressão de unicidade sem DOM: instâncias com prefixos
 * distintos nunca colidem, e dentro da instância cada tabId gera par único.
 */
export function tabDomIds(prefix: string, tabId: string): { tab: string; panel: string } {
  // encodeURIComponent é INJETIVO (sem colisão: "a b" ≠ "a_b" ≠ "a%20b");
  // IDs de HTML5 aceitam qualquer caractere exceto espaço, e o encode nunca
  // produz espaço. O prefixo do useId (":r1:") fica fora da codificação.
  const safe = `${prefix}-${encodeURIComponent(tabId)}`;
  return { tab: `ds-tab-${safe}`, panel: `ds-panel-${safe}` };
}

/**
 * Roving tabindex das Tabs: próxima aba para uma tecla de seta/Home/End.
 * Retorna o índice atual para teclas irrelevantes. Wrap nas extremidades
 * (padrão WAI-ARIA tabs).
 */
export function rovingNextIndex(current: number, count: number, key: string): number {
  if (count <= 0) return -1;
  switch (key) {
    case "ArrowRight":
    case "ArrowDown":
      return (current + 1) % count;
    case "ArrowLeft":
    case "ArrowUp":
      return (current - 1 + count) % count;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return current;
  }
}
