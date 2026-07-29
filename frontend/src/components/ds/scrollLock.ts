"use client";

/**
 * Coordenador ÚNICO de scroll lock. O Dialog da fundação (ds/Dialog) e o drawer
 * mobile do shell (shell/useDrawerA11y) pedem o lock por aqui — nenhum dos dois
 * mexe em `style.overflow` por conta própria.
 *
 * Por que centralizar: cada consumidor salvava e restaurava o inline style por
 * si. Com dois locks vivos (drawer + Dialog, ou Dialog sobre Dialog) o segundo
 * fotografava "hidden" — o valor que o primeiro tinha acabado de escrever. Daí:
 *  - liberando FORA de ordem (fecha o drawer antes do Dialog), o primeiro
 *    cleanup restaurava o valor original e o scroll destravava com o Dialog
 *    ainda aberto;
 *  - a liberação seguinte gravava "hidden" de volta — página travada para
 *    sempre, sem nenhum overlay aberto.
 *
 * Contrato: a PRIMEIRA aquisição fotografa os inline styles do `body` e da
 * `.screen` (o scroller REAL do shell — no desktop o body não rola) e aplica
 * `overflow:hidden`; a ÚLTIMA liberação restaura exatamente essa fotografia.
 * Liberações intermediárias, em QUALQUER ordem, não tocam no DOM. O `release`
 * devolvido é idempotente — chamá-lo duas vezes não libera o lock de outro dono.
 */

type Snapshot = { el: HTMLElement; overflow: string };

const owners = new Set<symbol>();
let snapshot: Snapshot[] = [];

/** Trava o scroll e devolve o release DESTE dono (idempotente). */
export function lockScroll(): () => void {
  const owner = Symbol("scroll-lock");

  if (owners.size === 0) {
    const screen = document.querySelector<HTMLElement>(".screen");
    const targets = screen ? [document.body, screen] : [document.body];
    snapshot = targets.map((el) => ({ el, overflow: el.style.overflow }));
    for (const { el } of snapshot) el.style.overflow = "hidden";
  }
  owners.add(owner);

  return () => {
    if (!owners.delete(owner)) return; // já liberado por este dono
    if (owners.size > 0) return; // ainda há dono: segue travado
    for (const { el, overflow } of snapshot) el.style.overflow = overflow;
    snapshot = [];
  };
}
