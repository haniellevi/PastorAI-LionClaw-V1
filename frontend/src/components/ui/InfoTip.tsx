"use client";

/**
 * Ícone "i" com popover de informação (hover/foco/clique). Usado na Topbar para
 * substituir o parágrafo descritivo que se repetia no cabeçalho de cada tela.
 */
import { useState } from "react";

export function InfoTip({ text, label = "Sobre esta tela" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className="infotip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="infotip-btn"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        i
      </button>
      {open ? (
        <span className="infotip-pop" role="tooltip">
          {text}
        </span>
      ) : null}
    </span>
  );
}
