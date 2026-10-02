"use client";

import { useEffect, useRef } from "react";

/** Arte separada da marca. Somente a decoração acompanha o pointer. */
export function MineralBackdrop({ compact = false }: { compact?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const art = ref.current;
    const surface = art?.closest<HTMLElement>("[data-mineral-surface]");
    if (!art || !surface || !window.matchMedia) return;
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let point = { x: 0, y: 0 };
    let suspended = false;
    let detach = () => {};

    function reset() {
      cancelAnimationFrame(frame);
      frame = 0;
      delete art!.dataset.tracking;
      art!.style.setProperty("--mineral-x", "0px");
      art!.style.setProperty("--mineral-y", "0px");
    }
    function editable(target: EventTarget | null) {
      return target instanceof Element && target.matches("input, textarea, select, [contenteditable='true']");
    }
    function configure() {
      detach();
      reset();
      if (!fine.matches || reduced.matches) return;
      suspended = editable(document.activeElement);
      const move = (event: PointerEvent) => {
        if (suspended || event.pointerType === "touch") return;
        const bounds = surface!.getBoundingClientRect();
        point = {
          x: Math.max(-6, Math.min(6, ((event.clientX - bounds.left) / bounds.width - 0.5) * 12)),
          y: Math.max(-6, Math.min(6, ((event.clientY - bounds.top) / bounds.height - 0.5) * 12)),
        };
        if (frame) return;
        frame = requestAnimationFrame(() => {
          frame = 0;
          art!.dataset.tracking = "true";
          art!.style.setProperty("--mineral-x", `${point.x}px`);
          art!.style.setProperty("--mineral-y", `${point.y}px`);
        });
      };
      const focus = (event: FocusEvent) => {
        if (editable(event.target)) { suspended = true; reset(); }
      };
      const blur = (event: FocusEvent) => { suspended = editable(event.relatedTarget); };
      surface!.addEventListener("pointermove", move, { passive: true });
      surface!.addEventListener("pointerleave", reset);
      surface!.addEventListener("focusin", focus);
      surface!.addEventListener("focusout", blur);
      detach = () => {
        surface!.removeEventListener("pointermove", move);
        surface!.removeEventListener("pointerleave", reset);
        surface!.removeEventListener("focusin", focus);
        surface!.removeEventListener("focusout", blur);
      };
    }
    configure();
    fine.addEventListener("change", configure);
    reduced.addEventListener("change", configure);
    return () => {
      detach();
      reset();
      fine.removeEventListener("change", configure);
      reduced.removeEventListener("change", configure);
    };
  }, []);

  return (
    <div ref={ref} className={`mineral-backdrop${compact ? " mineral-backdrop--compact" : ""}`} aria-hidden="true">
      <span className="mineral-facet mineral-facet--one" />
      <span className="mineral-facet mineral-facet--two" />
    </div>
  );
}
